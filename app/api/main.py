import logging
import os
from datetime import timedelta
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, StreamingResponse
from telethon.errors import SessionPasswordNeededError
from telethon.errors.common import AuthKeyNotFound
from telethon.errors.rpcbaseerrors import ServerError

from app.api.auth import require_admin, require_api_key
from app.core.config import settings
from app.core.db import async_session
from app.core.logging import setup_logging
from app.models.db import AddJob
from app.services.accounts import AccountService
from app.services.admins import AdminService, verify_password
from app.services.control import AppControlService
from app.services.jobs import JobService
from app.services.scraper import Scraper
from app.services.telethon_client import ClientFactory

app = FastAPI(title="Telegram Scraper & Adder API")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))
if settings.SECRET_KEY:
    app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
control = AppControlService()
admin_svc = AdminService()

setup_logging(settings.LOG_LEVEL)


@app.get("/health")
def health():
    return {"status": "ok"}


class EnqueueRequest(BaseModel):
    dest: str
    usernames: list[str]


@app.post("/jobs/enqueue")
async def enqueue(req: EnqueueRequest, _: bool = Depends(require_api_key)):
    svc = JobService()
    count = await svc.enqueue(req.dest, req.usernames)
    return {"enqueued": count}


@app.get("/jobs")
async def jobs(status: str | None = None, _: bool = Depends(require_api_key)):
    svc = JobService()
    items = await svc.list_jobs(status)
    return [
        {
            "id": j.id,
            "dest": j.dest_group,
            "username": j.username,
            "status": j.status,
            "account_id": j.account_id,
            "error": j.error,
        }
        for j in items
    ]


@app.get("/accounts")
async def accounts(_: bool = Depends(require_api_key)):
    svc = AccountService()
    items = await svc.list()
    return [
        {"id": a.id, "phone": a.phone, "cooldown_until": a.cooldown_until, "last_error": a.last_error} for a in items
    ]


class ScrapeQuery(BaseModel):
    source: str
    limit: int = 1000
    query: str = ""
    min_last_seen_days: int | None = None
    exclude_contains: list[str] = []
    include_full: bool = False


@app.post("/scrape")
async def scrape(q: ScrapeQuery, _: bool = Depends(require_api_key)):
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    # Use a temporary copy of the default session to avoid SQLite "database is locked" errors
    tmp_path = None
    base = os.path.join(settings.SESSIONS_DIR, "default")
    src = base + ".session" if os.path.exists(base + ".session") else (base if os.path.exists(base) else None)
    if src:
        import shutil
        import tempfile

        fd, tmp = tempfile.mkstemp(prefix="session_export_", suffix=".session")
        try:
            import os as _os

            _os.close(fd)
        except Exception as e:  # noqa: BLE001 - broad for cleanup safety
            logging.getLogger(__name__).debug("tmp fd close failed: %s", e)
        shutil.copyfile(src, tmp)
        tmp_path = tmp
        client = factory.build(tmp_path)
    else:
        client = factory.build("default")
    await client.start()
    try:
        scraper = Scraper(client)
        delta = timedelta(days=q.min_last_seen_days) if q.min_last_seen_days else None
        if q.include_full:
            usernames = await scraper.scrape_members_detailed(
                q.source, q.limit, q.query, min_last_seen=delta, include_full=True
            )
        else:
            usernames = await scraper.scrape_usernames(q.source, q.limit, q.query, min_last_seen=delta)
        if q.exclude_contains:
            lowered = [s.lower() for s in q.exclude_contains]
            usernames = [u for u in usernames if all(x not in u.lower() for x in lowered)]
        return {"count": len(usernames), "usernames": usernames}
    finally:
        try:
            await client.disconnect()
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception as e:  # noqa: BLE001 - best-effort cleanup
                    logging.getLogger(__name__).debug("tmp session cleanup failed: %s", e)


# Prometheus metrics
requests_total = Counter("app_requests_total", "Total API requests", ["endpoint"])  # minimal sample


@app.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/events/jobs")
async def jobs_events(_: bool = Depends(require_admin)):
    async def event_stream():
        import asyncio

        while True:
            # simple heartbeat to trigger client refreshes
            yield "data: tick\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/")
async def admin_page(request: Request, _: bool = Depends(require_admin)):
    authed = request.session.get("admin") is True
    # ensure CSRF token
    if authed and not request.session.get("csrf"):
        import secrets

        request.session["csrf"] = secrets.token_hex(16)
    accounts = await AccountService().list()
    return templates.TemplateResponse(
        "index.html", {"request": request, "authed": authed, "csrf": request.session.get("csrf"), "accounts": accounts}
    )


@app.get("/partials/overview")
async def overview_partial(request: Request, _: bool = Depends(require_admin)):
    # paused state
    paused = (await control.get("paused")) == "1"
    # worker heartbeat
    worker_alive = False
    try:
        hb = await control.get("worker_heartbeat")
        if hb:
            from datetime import datetime, timedelta

            ts = datetime.fromisoformat(hb)
            worker_alive = (datetime.utcnow() - ts) < timedelta(seconds=15)
    except Exception as e:  # noqa: BLE001 - heartbeat is best-effort
        logging.getLogger(__name__).debug("heartbeat read failed: %s", e)
    # accounts count
    accounts = 0
    try:
        accounts = len(await AccountService().list())
    except Exception:
        accounts = 0
    # job counts
    counts = await JobService().counts_by_status()
    return templates.TemplateResponse(
        "_overview.html",
        {"request": request, "paused": paused, "worker_alive": worker_alive, "accounts": accounts, "counts": counts},
    )


@app.get("/settings")
async def settings_page(request: Request, _: bool = Depends(require_admin)):
    # read current settings snapshot (subset that's safe to show)
    cfg = {
        "TELEGRAM_API_ID": settings.TELEGRAM_API_ID or "",
        "TELEGRAM_API_HASH": (settings.TELEGRAM_API_HASH[:6] + "…") if settings.TELEGRAM_API_HASH else "",
        "SESSIONS_DIR": settings.SESSIONS_DIR,
        "HTTP_PROXY": settings.HTTP_PROXY or "",
        "SOCKS_PROXY": settings.SOCKS_PROXY or "",
        "RATE_LIMIT_MAX": settings.RATE_LIMIT_MAX,
        "RATE_LIMIT_WINDOW": settings.RATE_LIMIT_WINDOW,
        "QUOTA_PER_ACCOUNT_MAX": settings.QUOTA_PER_ACCOUNT_MAX,
        "QUOTA_PER_ACCOUNT_WINDOW": settings.QUOTA_PER_ACCOUNT_WINDOW,
    }
    return templates.TemplateResponse(
        "settings.html", {"request": request, "cfg": cfg, "csrf": request.session.get("csrf")}
    )


@app.post("/settings")
async def settings_save(request: Request, _: bool = Depends(require_admin)):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    # update .env (append or replace lines for specific keys)
    env_path = os.path.join(os.getcwd(), ".env")
    updates = {
        "TELEGRAM_API_ID": str(form.get("TELEGRAM_API_ID", "")).strip(),
        "TELEGRAM_API_HASH": str(form.get("TELEGRAM_API_HASH", "")).strip(),
        "HTTP_PROXY": str(form.get("HTTP_PROXY", "")).strip(),
        "SOCKS_PROXY": str(form.get("SOCKS_PROXY", "")).strip(),
        "SESSIONS_DIR": str(form.get("SESSIONS_DIR", "")).strip() or settings.SESSIONS_DIR,
        "RATE_LIMIT_MAX": str(form.get("RATE_LIMIT_MAX", settings.RATE_LIMIT_MAX)),
        "RATE_LIMIT_WINDOW": str(form.get("RATE_LIMIT_WINDOW", settings.RATE_LIMIT_WINDOW)),
        "QUOTA_PER_ACCOUNT_MAX": str(form.get("QUOTA_PER_ACCOUNT_MAX", settings.QUOTA_PER_ACCOUNT_MAX)),
        "QUOTA_PER_ACCOUNT_WINDOW": str(form.get("QUOTA_PER_ACCOUNT_WINDOW", settings.QUOTA_PER_ACCOUNT_WINDOW)),
    }
    # read existing
    existing = {}
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.rstrip().split("=", 1)
                    existing[k] = v
    except FileNotFoundError:
        pass
    existing.update({k: v for k, v in updates.items() if v != ""})
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    # naive reload note
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/admin/accounts")
async def accounts_page(request: Request, _: bool = Depends(require_admin)):
    svc = AccountService()
    items = await svc.list()
    return templates.TemplateResponse(
        "accounts.html", {"request": request, "accounts": items, "csrf": request.session.get("csrf")}
    )


@app.post("/admin/accounts/delete")
async def accounts_delete(request: Request, id: int = Form(...), _: bool = Depends(require_admin)):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    svc = AccountService()
    await svc.delete(id)
    return RedirectResponse(url="/admin/accounts", status_code=303)


@app.get("/admin/accounts/login")
async def accounts_login_form(request: Request, _: bool = Depends(require_admin)):
    return templates.TemplateResponse("login_account.html", {"request": request, "csrf": request.session.get("csrf")})


@app.post("/admin/accounts/login")
async def accounts_login(request: Request, phone: str = Form(...), _: bool = Depends(require_admin)):
    # Start login flow: send code via Telethon and store in session temp
    from app.services.telethon_client import ClientFactory, parse_proxy

    if request.session.get("csrf") != (await request.form()).get("csrf"):
        return Response(status_code=403)
    # Ensure API credentials are configured to avoid runtime 500s
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        return templates.TemplateResponse(
            "login_account.html",
            {
                "request": request,
                "csrf": request.session.get("csrf"),
                "error": "Telegram API ID and API HASH are required. Set them in Settings, then retry.",
            },
            status_code=400,
        )
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build(phone, proxy=parse_proxy(settings.SOCKS_PROXY or settings.HTTP_PROXY))
    await client.connect()
    try:
        try:
            sent = await client.send_code_request(phone)
        except ServerError as e:
            # Common in restricted networks: "No workers running". Guide user to set a proxy.
            return templates.TemplateResponse(
                "login_account.html",
                {
                    "request": request,
                    "csrf": request.session.get("csrf"),
                    "error": (
                        f"Telegram servers temporarily unavailable ({str(e)}). "
                        "Try again in a minute or set an HTTP/SOCKS proxy in Settings, then retry."
                    ),
                },
                status_code=503,
            )
        request.session["tg_login_phone"] = phone
        request.session["tg_login_hash"] = sent.phone_code_hash
        return templates.TemplateResponse(
            "login_account_code.html",
            {"request": request, "phone": phone, "csrf": request.session.get("csrf")},
        )
    finally:
        await client.disconnect()


@app.post("/admin/accounts/verify")
async def accounts_verify(request: Request, code: str = Form(...), _: bool = Depends(require_admin)):
    from app.services.telethon_client import ClientFactory, parse_proxy

    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    phone = request.session.get("tg_login_phone")
    code_hash = request.session.get("tg_login_hash")
    if not phone or not code_hash:
        return RedirectResponse(url="/admin/accounts/login", status_code=303)
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build(phone, proxy=parse_proxy(settings.SOCKS_PROXY or settings.HTTP_PROXY))
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        except ServerError as e:
            return templates.TemplateResponse(
                "login_account_code.html",
                {
                    "request": request,
                    "phone": phone,
                    "csrf": request.session.get("csrf"),
                    "error": (
                        f"Telegram servers temporarily unavailable ({str(e)}). "
                        "Try again later or configure a proxy in Settings."
                    ),
                },
                status_code=503,
            )
        except SessionPasswordNeededError:
            # ask for 2FA password
            return templates.TemplateResponse(
                "login_account_password.html",
                {"request": request, "phone": phone, "csrf": request.session.get("csrf")},
            )
        # persist account in DB
        await AccountService().create(phone=phone, session_path=os.path.join(settings.SESSIONS_DIR, phone))
        # cleanup temp
        request.session.pop("tg_login_phone", None)
        request.session.pop("tg_login_hash", None)
        return RedirectResponse(url="/admin/accounts", status_code=303)
    finally:
        await client.disconnect()


@app.post("/admin/accounts/password")
async def accounts_password(request: Request, password: str = Form(...), _: bool = Depends(require_admin)):
    from app.services.telethon_client import ClientFactory, parse_proxy

    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    phone = request.session.get("tg_login_phone")
    if not phone:
        return RedirectResponse(url="/admin/accounts/login", status_code=303)
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build(phone, proxy=parse_proxy(settings.SOCKS_PROXY or settings.HTTP_PROXY))
    await client.connect()
    try:
        try:
            await client.sign_in(password=password)
        except ServerError as e:
            return templates.TemplateResponse(
                "login_account_password.html",
                {
                    "request": request,
                    "phone": phone,
                    "csrf": request.session.get("csrf"),
                    "error": f"Telegram servers temporarily unavailable ({str(e)}). Try again later or set a proxy.",
                },
                status_code=503,
            )
        await AccountService().create(phone=phone, session_path=os.path.join(settings.SESSIONS_DIR, phone))
        request.session.pop("tg_login_phone", None)
        request.session.pop("tg_login_hash", None)
        return RedirectResponse(url="/admin/accounts", status_code=303)
    finally:
        await client.disconnect()


@app.get("/scrape")
async def scrape_page(request: Request, _: bool = Depends(require_admin)):
    accounts = await AccountService().list()
    return templates.TemplateResponse(
        "scrape.html", {"request": request, "csrf": request.session.get("csrf"), "results": None, "accounts": accounts}
    )


@app.post("/scrape/run")
async def scrape_run(
    request: Request,
    source: str = Form(...),
    limit: int = Form(500),
    query: str = Form(""),
    min_last_seen_days: Optional[int] = Form(None),
    exclude_contains: Optional[str] = Form(""),
    include_full: Optional[int] = Form(None),
    skip_bots: Optional[int] = Form(1),
    skip_admins: Optional[int] = Form(1),
    _: bool = Depends(require_admin),
):
    if request.session.get("csrf") != (await request.form()).get("csrf"):
        return Response(status_code=403)
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    client = factory.build("default")
    await client.start()
    try:
        scraper = Scraper(client)
        delta = timedelta(days=min_last_seen_days) if min_last_seen_days else None
        if include_full:
            usernames = await scraper.scrape_members_detailed(
                source,
                limit=limit,
                query=query,
                min_last_seen=delta,
                skip_bots=bool(skip_bots),
                skip_admins=bool(skip_admins),
                include_full=True,
            )
        else:
            usernames = await scraper.scrape_usernames(source, limit, query, min_last_seen=delta)
        exc = [s.strip().lower() for s in (exclude_contains or "").split(",") if s.strip()]
        if exc:
            usernames = [u for u in usernames if all(x not in u.lower() for x in exc)]
        accounts = await AccountService().list()
        return templates.TemplateResponse(
            "scrape.html",
            {
                "request": request,
                "csrf": request.session.get("csrf"),
                "results": usernames,
                "source": source,
                "limit": limit,
                "query": query,
                "min_last_seen_days": min_last_seen_days or "",
                "exclude_contains": exclude_contains or "",
                "include_full": bool(include_full),
                "skip_bots": bool(skip_bots),
                "skip_admins": bool(skip_admins),
                "accounts": accounts,
            },
        )
    finally:
        await client.disconnect()


@app.post("/scrape/enqueue")
async def scrape_enqueue(
    request: Request, dest: str = Form(...), usernames: str = Form(...), _: bool = Depends(require_admin)
):
    if request.session.get("csrf") != (await request.form()).get("csrf"):
        return Response(status_code=403)
    lines = [u for u in usernames.splitlines() if u.strip()]
    us, phs = JobService.parse_mixed_lines(lines)
    if us or phs:
        form = await request.form()
        account_ids = [int(x) for x in form.getlist("account_ids")] if hasattr(form, "getlist") else []
        await JobService().enqueue(dest, usernames=us, phones=phs, allowed_account_ids=account_ids or None)
    return RedirectResponse(url="/", status_code=303)


@app.get("/message")
async def message_page(request: Request, _: bool = Depends(require_admin)):
    accounts = await AccountService().list()
    return templates.TemplateResponse(
        "message.html", {"request": request, "csrf": request.session.get("csrf"), "accounts": accounts}
    )


@app.post("/message/enqueue")
async def message_enqueue(request: Request, _: bool = Depends(require_admin)):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    targets = [t.strip() for t in str(form.get("targets", "")).splitlines() if t.strip()]
    messages = [m.strip() for m in str(form.get("messages", "")).splitlines() if m.strip()]
    account_ids = [int(x) for x in form.getlist("account_ids")] if hasattr(form, "getlist") else []
    users, phones = JobService.parse_mixed_lines(targets)
    if not messages:
        messages = ["Hello!"]
    from uuid import uuid4

    batch = uuid4().hex[:12]
    await JobService().enqueue(
        dest_group="",
        usernames=users,
        phones=phones,
        kind="message",
        allowed_account_ids=account_ids or None,
        batch_id=batch,
        message_text="\n".join(messages),
    )
    return RedirectResponse(url="/", status_code=303)


@app.get("/onboarding")
async def onboarding(request: Request, _: bool = Depends(require_admin)):
    # compute readiness checks
    checks = {
        "secret_key": bool(settings.SECRET_KEY),
        "api_id": bool(settings.TELEGRAM_API_ID),
        "api_hash": bool(settings.TELEGRAM_API_HASH),
        "sessions_dir": os.path.isdir(settings.SESSIONS_DIR),
        "accounts": False,
        "worker_alive": False,
    }
    try:
        checks["accounts"] = len(await AccountService().list()) > 0
    except Exception:
        checks["accounts"] = False
    try:
        hb = await control.get("worker_heartbeat")
        if hb:
            from datetime import datetime, timedelta

            ts = datetime.fromisoformat(hb)
            checks["worker_alive"] = (datetime.utcnow() - ts) < timedelta(seconds=15)
    except Exception as e:  # noqa: BLE001 - best-effort
        logging.getLogger(__name__).debug("heartbeat read failed: %s", e)
    cfg = {"SESSIONS_DIR": settings.SESSIONS_DIR}
    return templates.TemplateResponse(
        "onboarding.html", {"request": request, "checks": checks, "csrf": request.session.get("csrf"), "cfg": cfg}
    )


@app.get("/upload")
async def upload_page(request: Request, _: bool = Depends(require_admin)):
    accounts = await AccountService().list()
    return templates.TemplateResponse(
        "upload.html", {"request": request, "csrf": request.session.get("csrf"), "accounts": accounts}
    )


@app.get("/contact")
async def contact_page(request: Request):
    return templates.TemplateResponse("contact.html", {"request": request})


@app.post("/upload")
async def upload_jobs(
    request: Request,
    dest: str = Form(...),
    file: UploadFile = File(...),
    _: bool = Depends(require_admin),  # noqa: B008
):
    if request.session.get("csrf") != (await request.form()).get("csrf"):
        return Response(status_code=403)
    content = (await file.read()).decode("utf-8", errors="ignore")
    # Accept CSV or plain lines; take first column, strip @
    usernames = []
    phones = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line:
            line = line.split(",", 1)[0]
        if line.startswith("@"):
            usernames.append(line.lstrip("@"))
        else:
            phones.append(line)
    if not (usernames or phones):
        return RedirectResponse(url="/upload", status_code=303)
    form = await request.form()
    account_ids = [int(x) for x in form.getlist("account_ids")] if hasattr(form, "getlist") else []
    await JobService().enqueue(dest, usernames=usernames, phones=phones, allowed_account_ids=account_ids or None)
    return RedirectResponse(url="/", status_code=303)


@app.get("/login")
async def login_form(request: Request):
    if not request.session.get("csrf"):
        import secrets

        request.session["csrf"] = secrets.token_hex(16)
    return templates.TemplateResponse("login.html", {"request": request, "csrf": request.session.get("csrf")})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), csrf: str = Form(...)):
    if request.session.get("csrf") != csrf:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid CSRF"}, status_code=403)
    svc = AdminService()
    user = await svc.get_by_username(username)
    ok = False
    if user and verify_password(password, user.password_hash):
        ok = True
    elif (
        settings.ADMIN_USERNAME
        and settings.ADMIN_PASSWORD
        and username == settings.ADMIN_USERNAME
        and password == settings.ADMIN_PASSWORD
    ):
        ok = True
    if ok:
        request.session["admin"] = True
        # Redirect so GET "/" can set/generate CSRF and render the fresh dashboard
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid credentials"}, status_code=401
    )


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return templates.TemplateResponse("login.html", {"request": request, "info": "Logged out"})


@app.get("/partials/jobs")
async def jobs_partial(
    request: Request,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
    q: str | None = None,
    dest: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    _: bool = Depends(require_admin),
):
    svc = JobService()
    df = None
    dt = None
    from datetime import datetime

    try:
        if date_from:
            df = datetime.fromisoformat(date_from)
        if date_to:
            dt = datetime.fromisoformat(date_to)
    except Exception:
        df = dt = None
    items, total = await svc.search_jobs(status or None, q, dest, df, dt, page, page_size)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": status or "all",
            "page": page,
            "page_size": page_size,
            "total": total,
            "q": q or "",
            "dest": dest or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
        },
    )


@app.post("/jobs/run-now")
async def job_run_now(request: Request, job_id: int = Form(...), _: bool = Depends(require_admin)):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    svc = JobService()
    job = await svc.get(job_id)
    if not job:
        return Response(status_code=404)
    # prioritize by setting next_attempt_at to past and status to queued
    from datetime import datetime, timedelta

    async with async_session() as session:
        db_job = await session.get(AddJob, job_id)
        if not db_job:
            return Response(status_code=404)
        db_job.status = "queued"
        db_job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db_job.updated_at = datetime.utcnow()
        await session.commit()
    # return refreshed jobs table
    items, total = await svc.search_jobs(status=None, page=1, page_size=25)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": total,
        },
    )


@app.post("/jobs/set-accounts")
async def job_set_accounts(
    request: Request, job_id: int = Form(...), account_ids: str = Form(""), _: bool = Depends(require_admin)
):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    ids = [int(x) for x in account_ids.split(",") if x.strip().isdigit()] if account_ids else []
    await JobService().set_allowed_accounts(job_id, ids or None)
    items, total = await JobService().search_jobs(status=None, page=1, page_size=25)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": total,
        },
    )


@app.post("/jobs/set-next")
async def job_set_next(
    request: Request, job_id: int = Form(...), seconds: int = Form(0), _: bool = Depends(require_admin)
):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    from datetime import datetime, timedelta

    async with async_session() as session:
        db_job = await session.get(AddJob, job_id)
        if not db_job:
            return Response(status_code=404)
        db_job.next_attempt_at = datetime.utcnow() + timedelta(seconds=int(seconds))
        db_job.updated_at = datetime.utcnow()
        await session.commit()
    items, total = await JobService().search_jobs(status=None, page=1, page_size=25)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": total,
        },
    )


@app.post("/jobs/mark-status")
async def job_mark_status(
    request: Request, job_id: int = Form(...), status: str = Form("success"), _: bool = Depends(require_admin)
):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    if status not in {"queued", "in_progress", "success", "failed", "skipped", "canceled"}:
        return Response(status_code=400)
    await JobService().mark(job_id, status)
    items, total = await JobService().search_jobs(status=None, page=1, page_size=25)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": total,
        },
    )


@app.post("/jobs/cancel")
async def jobs_cancel(request: Request, job_ids: str = Form(""), _: bool = Depends(require_admin)):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    ids = [int(x) for x in (job_ids.split(",") if job_ids else []) if x.strip().isdigit()]
    await JobService().cancel_jobs(ids)
    items, total = await JobService().search_jobs(status=None, page=1, page_size=25)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": total,
        },
    )


@app.post("/jobs/cancel-all")
async def jobs_cancel_all(request: Request, _: bool = Depends(require_admin)):
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    await JobService().cancel_all()
    items, total = await JobService().search_jobs(status=None, page=1, page_size=25)
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": total,
        },
    )


@app.post("/jobs/enqueue-form")
async def enqueue_form(request: Request, _: bool = Depends(require_admin)):
    form = await request.form()
    # CSRF check
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    dest = str(form.get("dest", "")).strip()
    raw = str(form.get("usernames", ""))
    lines = [u for u in raw.splitlines() if u.strip()]
    usernames, phones = JobService.parse_mixed_lines(lines)
    svc = JobService()
    if dest and (usernames or phones):
        account_ids = [int(x) for x in form.getlist("account_ids")] if hasattr(form, "getlist") else []
        await svc.enqueue(dest, usernames=usernames, phones=phones, allowed_account_ids=account_ids or None)
    items = await svc.list_jobs()
    paused = (await control.get("paused")) == "1"
    return templates.TemplateResponse(
        "_jobs_table.html",
        {
            "request": request,
            "csrf": request.session.get("csrf"),
            "jobs": items,
            "paused": paused,
            "status": "all",
            "page": 1,
            "page_size": 25,
            "total": len(items),
        },
    )


@app.get("/partials/recent")
async def recent_partial(request: Request, _: bool = Depends(require_admin)):
    svc = JobService()
    items, _ = await svc.search_jobs(status=None, page=1, page_size=10)
    # Show latest by updated_at
    items = sorted(items, key=lambda j: j.updated_at or j.created_at, reverse=True)[:10]
    return templates.TemplateResponse("_recent.html", {"request": request, "items": items})


@app.get("/inbox")
async def inbox_page(request: Request, _: bool = Depends(require_admin)):
    accounts = await AccountService().list()
    sel = request.query_params.get("account_id")
    account_id = int(sel) if sel and sel.isdigit() else (accounts[0].id if accounts else None)
    return templates.TemplateResponse(
        "inbox.html",
        {"request": request, "csrf": request.session.get("csrf"), "accounts": accounts, "account_id": account_id},
    )


@app.get("/partials/inbox")
async def inbox_partial(
    request: Request,
    account_id: int,
    limit: int = 50,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    _: bool = Depends(require_admin),
):
    # Build a client for the selected account and fetch recent incoming messages
    acc = await AccountService().get(account_id)
    if not acc:
        return Response("Account not found", status_code=404)
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    from app.services.telethon_client import parse_proxy

    proxy = acc.proxy or settings.SOCKS_PROXY or settings.HTTP_PROXY
    # Explicitly use the stored session_path for this account to avoid mismatches
    session_id = acc.session_path if acc.session_path else acc.phone
    client = factory.build(session_id, proxy=parse_proxy(proxy), device_string=acc.device_string)
    # Early check for session presence
    import os

    base = session_id
    has_session_file = os.path.exists(base) or os.path.exists(base + ".session")
    error = None
    try:
        await client.start()
    except AuthKeyNotFound:
        error = "Session is invalid or expired. Please re-login this account from Admin → Accounts."
    except ServerError as e:
        error = f"Telegram servers temporarily unavailable ({str(e)}). Try again in a minute."
    try:
        # Aggregate latest incoming messages across recent dialogs
        items = []
        if error:
            return templates.TemplateResponse(
                "_inbox.html", {"request": request, "items": items, "account_id": account_id, "error": error}
            )
        if not has_session_file:
            return templates.TemplateResponse(
                "_inbox.html",
                {
                    "request": request,
                    "items": items,
                    "account_id": account_id,
                    "error": "No session file found for this account. Login first in Admin → Accounts.",
                },
            )
        per_dialog = max(1, min(5, limit // 10 or 1))
        async for d in client.iter_dialogs(limit=100):
            # pull a few recent messages per dialog
            fetched = 0
            async for msg in client.iter_messages(d.entity, limit=per_dialog):
                if getattr(msg, "out", False):
                    continue  # only incoming
                date = getattr(msg, "date", None)
                text = (msg.message or "").strip()
                if not text:
                    if getattr(msg, "media", None):
                        text = "[media]"
                    elif getattr(msg, "action", None):
                        text = "[service]"
                    else:
                        text = "[empty]"
                peer_name = (
                    getattr(d, "name", None)
                    or getattr(d.entity, "title", None)
                    or getattr(d.entity, "username", None)
                    or str(getattr(d.entity, "id", ""))
                )
                # Try to resolve sender info for groups/channels
                sender_disp = None
                try:
                    s = getattr(msg, "sender", None)
                    if getattr(d, "is_user", False):
                        sender_disp = peer_name
                    elif s:
                        sender_disp = (
                            getattr(s, "username", None)
                            or ((getattr(s, "first_name", "") + " " + getattr(s, "last_name", "")).strip())
                            or str(getattr(s, "id", ""))
                        )
                except Exception:
                    sender_disp = None
                items.append(
                    {
                        "peer": str(peer_name),
                        "sender": str(sender_disp) if sender_disp else "",
                        "text": text,
                        "date": date.isoformat() if date else "",
                        "_ts": date.timestamp() if date else 0.0,
                    }
                )
                fetched += 1
                if fetched >= per_dialog:
                    break
            if len(items) >= limit * 2:
                break
        # Sort by date desc and take top 'limit'
        items.sort(key=lambda x: x.get("_ts", 0.0), reverse=True)
        items = items[:limit]
        # Query filter
        if q:
            ql = str(q).lower()
            items = [
                it
                for it in items
                if ql in (it.get("text", "").lower())
                or ql in (it.get("peer", "").lower())
                or ql in (it.get("sender", "").lower())
            ]
        # Pagination
        total = len(items)
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        start = (page - 1) * page_size
        end = start + page_size
        page_items = items[start:end]
    finally:
        await client.disconnect()
    return templates.TemplateResponse(
        "_inbox.html",
        {
            "request": request,
            "items": page_items,
            "account_id": account_id,
            "q": q or "",
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@app.post("/scrape/export")
async def scrape_export(
    request: Request,
    source: str = Form(...),
    limit: int = Form(500),
    query: str = Form(""),
    min_last_seen_days: Optional[int] = Form(None),
    exclude_contains: Optional[str] = Form(""),
    skip_bots: Optional[int] = Form(1),
    skip_admins: Optional[int] = Form(1),
    _: bool = Depends(require_admin),
):
    # CSRF check
    form = await request.form()
    if request.session.get("csrf") != form.get("csrf"):
        return Response(status_code=403)
    # Build client (use temporary copy of default session to avoid SQLite lock)
    factory = ClientFactory(settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH, settings.SESSIONS_DIR)
    tmp_path = None
    base = os.path.join(settings.SESSIONS_DIR, "default")
    src = base + ".session" if os.path.exists(base + ".session") else (base if os.path.exists(base) else None)
    if src:
        import shutil
        import tempfile

        fd, tmp = tempfile.mkstemp(prefix="session_export_", suffix=".session")
        try:
            import os as _os

            _os.close(fd)
        except Exception as e:  # noqa: BLE001
            logging.getLogger(__name__).debug("tmp fd close failed: %s", e)
        shutil.copyfile(src, tmp)
        tmp_path = tmp
        client = factory.build(tmp_path)
    else:
        client = factory.build("default")
    await client.start()
    try:
        scraper = Scraper(client)
        delta = (
            timedelta(days=int(min_last_seen_days))
            if (min_last_seen_days is not None and str(min_last_seen_days).strip() != "")
            else None
        )
        rows = await scraper.scrape_members_detailed(
            source,
            limit=limit,
            query=query,
            min_last_seen=delta,
            skip_bots=bool(int(skip_bots) if isinstance(skip_bots, (int, str)) else skip_bots),
            skip_admins=bool(int(skip_admins) if isinstance(skip_admins, (int, str)) else skip_admins),
            include_full=True,
        )
        # Optional exclude filter (applies to username)
        exc = [s.strip().lower() for s in (exclude_contains or "").split(",") if s.strip()]
        if exc:

            def keep(r):
                uname = (r.get("username") or "").lower()
                return all(x not in uname for x in exc)

            rows = [r for r in rows if keep(r)]
        # Build CSV
        import csv
        import io
        import re

        output = io.StringIO(newline="")
        fieldnames = [
            "id",
            "username",
            "phone",
            "first_name",
            "last_name",
            "full_name",
            "is_bot",
            "is_verified",
            "is_premium",
            "is_restricted",
            "lang_code",
            "status",
            "last_seen",
            "about",
            "common_chats_count",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        # Prepare filename
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", source)
        content = output.getvalue()
        headers = {"Content-Disposition": f"attachment; filename=members_{safe}.csv"}
        return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)
    finally:
        try:
            await client.disconnect()
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception as e:  # noqa: BLE001
                    logging.getLogger(__name__).debug("tmp session cleanup failed: %s", e)


@app.post("/control/pause")
async def pause(request: Request, _: bool = Depends(require_admin)):
    if request.session.get("csrf") != (await request.form()).get("csrf"):
        return Response(status_code=403)
    await control.set("paused", "1")
    return {"ok": True}


@app.post("/control/resume")
async def resume(request: Request, _: bool = Depends(require_admin)):
    if request.session.get("csrf") != (await request.form()).get("csrf"):
        return Response(status_code=403)
    await control.set("paused", "0")
    return {"ok": True}
