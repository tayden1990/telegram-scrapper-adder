import asyncio
import logging
import random
from datetime import datetime
from typing import Dict

from telethon.errors import FloodWaitError, PeerFloodError
from telethon.errors.rpcbaseerrors import ServerError

from app.core.config import settings
from app.core.db import init_db
from app.core.limits import Quotas, RateLimiter
from app.core.metrics import jobs_total
from app.services.accounts import AccountService
from app.services.adder import Adder
from app.services.control import AppControlService
from app.services.jobs import JobService
from app.services.telethon_client import ClientFactory, parse_proxy


async def run_worker():
    await init_db()
    jobsvc = JobService()
    accsvc = AccountService()
    ctrl = AppControlService()
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)

    # cache of active clients per account_id
    clients: Dict[int, tuple] = {}

    async def get_client_for_account(acc):
        # return cached client/adder if already started
        if acc.id in clients:
            return clients[acc.id]
        # fallback to global proxy settings if account has none
        proxy = acc.proxy or settings.SOCKS_PROXY or settings.HTTP_PROXY
        session_id = acc.session_path if getattr(acc, "session_path", None) else acc.phone
        client = factory.build(session_id, proxy=parse_proxy(proxy), device_string=acc.device_string)
        await client.start()
        adder = Adder(client)
        clients[acc.id] = (client, adder)
        return clients[acc.id]

    # global rate limiter and per-account quotas
    rl = RateLimiter(max_events=settings.RATE_LIMIT_MAX, per_seconds=settings.RATE_LIMIT_WINDOW)
    quotas = Quotas(max_per_window=settings.QUOTA_PER_ACCOUNT_MAX, window_seconds=settings.QUOTA_PER_ACCOUNT_WINDOW)

    last_hb = 0
    while True:
        # honor pause flag
        try:
            paused = (await ctrl.get("paused")) == "1"
        except Exception:
            paused = False
        if paused:
            await asyncio.sleep(2)
            continue
        # update worker heartbeat every ~5 seconds
        now_ts = int(asyncio.get_event_loop().time())
        if now_ts - last_hb >= 5:
            try:
                await ctrl.set("worker_heartbeat", datetime.utcnow().isoformat())
            except Exception as e:  # noqa: BLE001 - best-effort heartbeat
                logging.getLogger(__name__).debug("heartbeat write failed: %s", e)
            last_hb = now_ts

        job = await jobsvc.next_due_job()
        if not job:
            await asyncio.sleep(2)
            continue

        # skip if scheduled in the future
        if job.next_attempt_at and job.next_attempt_at > datetime.utcnow():
            await asyncio.sleep(2)
            continue
        # skip canceled jobs (terminal state)
        if job.status == "canceled":
            await asyncio.sleep(1)
            continue

        accounts = await accsvc.available_accounts()
        # filter by allowed_account_ids if present
        if job.allowed_account_ids:
            allowed = {int(x) for x in job.allowed_account_ids.split(",") if x.strip().isdigit()}
            accounts = [a for a in accounts if a.id in allowed]
        if not accounts:
            await asyncio.sleep(5)
            continue

        # rotation: pick random available account
        acc = random.choice(accounts)  # noqa: S311
        client, adder = await get_client_for_account(acc)
        try:
            # show progress in UI
            await jobsvc.mark_in_progress(job.id, account_id=acc.id)
            if not (job.username or job.phone):
                await jobsvc.mark(job.id, "failed", account_id=acc.id, error="missing username/phone")
                jobs_total.labels(status="failed").inc()
                await asyncio.sleep(1)
                continue

            # rate-limit and quota
            if not rl.allow() or not quotas.allow(str(acc.id)):
                await asyncio.sleep(1)
                continue

            if job.kind == "message":
                msgs = (job.message_text or "Hello!").splitlines()
                if job.username:
                    # resolve username to peer and send
                    result = {"success": 0, "skipped": 0, "failed": 0, "error": None}
                    try:
                        text = random.choice(msgs)  # noqa: S311
                        peer = await client.get_entity(job.username)
                        await client.send_message(peer, text)
                        result["success"] = 1
                    except Exception as e:
                        result["failed"] = 1
                        result["error"] = str(e)
                else:
                    result = await adder.send_messages_to_phones([job.phone], msgs)
            else:
                if job.username:
                    result = await adder.add_usernames(job.dest_group, [job.username])
                else:
                    result = await adder.add_phones(job.dest_group, [job.phone])
            if result.get("success", 0) > 0:
                await jobsvc.mark(job.id, "success", account_id=acc.id)
                jobs_total.labels(status="success").inc()
            elif result.get("skipped", 0) > 0:
                await jobsvc.mark(job.id, "skipped", account_id=acc.id, error=result.get("error"))
                jobs_total.labels(status="skipped").inc()
            else:
                await jobsvc.mark(job.id, "failed", account_id=acc.id, error=(result.get("error") or "unknown"))
                jobs_total.labels(status="failed").inc()
        except (FloodWaitError, PeerFloodError) as e:
            # apply cooldown to this account and requeue the job
            await accsvc.set_cooldown(acc.id, seconds=3600, last_error=str(e))
            backoff = min(3600, 2 ** min((job.attempt or 0) + 1, 8))
            await jobsvc.schedule_retry(job.id, backoff)
            jobs_total.labels(status="failed").inc()
            await asyncio.sleep(1)
        except ServerError:
            # transient Telegram internal issue; retry soon
            backoff = min(300, 2 ** min((job.attempt or 0) + 1, 6))
            await jobsvc.schedule_retry(job.id, backoff)
            jobs_total.labels(status="failed").inc()
            await asyncio.sleep(1)
        except Exception as e:
            await jobsvc.mark(job.id, "failed", account_id=acc.id, error=str(e))
            jobs_total.labels(status="failed").inc()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
