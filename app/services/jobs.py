from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from sqlmodel import func, select

from app.core.db import async_session
from app.models.db import AddJob


class JobService:
    async def get(self, job_id: int) -> Optional[AddJob]:
        async with async_session() as session:
            return await session.get(AddJob, job_id)

    async def enqueue(
        self,
        dest_group: str,
        usernames: Iterable[str] = (),
        phones: Iterable[str] = (),
        kind: str = "add",
        allowed_account_ids: Optional[Sequence[int]] = None,
        batch_id: Optional[str] = None,
        message_text: Optional[str] = None,
    ) -> int:
        async with async_session() as session:
            jobs = []
            for u in usernames:
                jobs.append(
                    AddJob(
                        dest_group=dest_group,
                        username=u,
                        status="queued",
                        created_at=datetime.utcnow(),
                        kind=kind,
                        allowed_account_ids=self._fmt_ids(allowed_account_ids),
                        batch_id=batch_id,
                        message_text=message_text,
                    )
                )
            for p in phones:
                jobs.append(
                    AddJob(
                        dest_group=dest_group,
                        phone=p,
                        status="queued",
                        created_at=datetime.utcnow(),
                        kind=kind,
                        allowed_account_ids=self._fmt_ids(allowed_account_ids),
                        batch_id=batch_id,
                        message_text=message_text,
                    )
                )
            # storing usernames without IDs here, could be extended to a Member table join
            session.add_all(jobs)
            await session.commit()
            return len(jobs)

    @staticmethod
    def parse_mixed_lines(lines: Sequence[str]) -> Tuple[List[str], List[str]]:
        """Split a mixed list of @usernames and phone numbers into separate lists."""
        users: List[str] = []
        phones: List[str] = []
        for raw in lines:
            s = raw.strip()
            if not s:
                continue
            if s.startswith("@"):
                users.append(s.lstrip("@"))
            else:
                # keep plus if present; strip spaces and dashes
                p = s.replace(" ", "").replace("-", "")
                if p.startswith("+"):
                    phones.append(p)
                elif p.isdigit():
                    phones.append(p)
                else:
                    # fallback treat as username if malformed
                    users.append(s.lstrip("@"))
        return users, phones

    @staticmethod
    def _fmt_ids(ids: Optional[Sequence[int]]) -> Optional[str]:
        if not ids:
            return None
        return ",".join(str(i) for i in ids)

    async def list_jobs(self, status: Optional[str] = None) -> List[AddJob]:
        async with async_session() as session:
            query = select(AddJob)
            if status:
                query = query.where(AddJob.status == status)
            res = await session.execute(query)
            return list(res.scalars().all())

    async def next_due_job(self) -> Optional[AddJob]:
        now = datetime.utcnow()
        async with async_session() as session:
            res = await session.execute(
                select(AddJob)
                .where(
                    (AddJob.status == "queued") & ((AddJob.next_attempt_at.is_(None)) | (AddJob.next_attempt_at <= now))
                )
                .order_by(AddJob.created_at)
            )
            return res.scalars().first()

    async def mark(self, job_id: int, status: str, account_id: Optional[int] = None, error: Optional[str] = None):
        async with async_session() as session:
            job = await session.get(AddJob, job_id)
            if not job:
                return
            job.status = status
            job.updated_at = datetime.utcnow()
            if account_id is not None:
                job.account_id = account_id
            job.error = error
            await session.commit()

    async def mark_in_progress(self, job_id: int, account_id: Optional[int] = None):
        async with async_session() as session:
            job = await session.get(AddJob, job_id)
            if not job:
                return
            job.status = "in_progress"
            job.updated_at = datetime.utcnow()
            if account_id is not None:
                job.account_id = account_id
            await session.commit()

    async def schedule_retry(self, job_id: int, delay_seconds: int):
        async with async_session() as session:
            job = await session.get(AddJob, job_id)
            if not job:
                return
            job.attempt = (job.attempt or 0) + 1
            job.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
            job.updated_at = datetime.utcnow()
            await session.commit()

    async def search_jobs(
        self,
        status: Optional[str] = None,
        q: Optional[str] = None,
        dest: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 25,
    ) -> Tuple[List[AddJob], int]:
        """Server-side filtered and paginated jobs list, returns (items, total)."""
        async with async_session() as session:
            filters = []
            if status and status != "all":
                filters.append(AddJob.status == status)
            if q:
                like = f"%{q}%"
                filters.append((AddJob.username.ilike(like)) | (AddJob.dest_group.ilike(like)))
            if dest:
                filters.append(AddJob.dest_group.ilike(f"%{dest}%"))
            if date_from:
                filters.append(AddJob.created_at >= date_from)
            if date_to:
                filters.append(AddJob.created_at <= date_to)

            base = select(AddJob)
            if filters:
                for f in filters:
                    base = base.where(f)

            # total count
            count_stmt = select(func.count()).select_from(AddJob)
            if filters:
                for f in filters:
                    count_stmt = count_stmt.where(f)
            total = (await session.execute(count_stmt)).scalar_one()

            # ordered page
            stmt = base.order_by(AddJob.created_at.desc()).offset(max(0, (page - 1) * page_size)).limit(page_size)
            items = list((await session.execute(stmt)).scalars().all())
            return items, total

    async def counts_by_status(self) -> dict:
        """Return counts per status plus total."""
        async with async_session() as session:
            rows = await session.execute(select(AddJob.status, func.count()).group_by(AddJob.status))
            counts = {"queued": 0, "in_progress": 0, "success": 0, "failed": 0, "skipped": 0, "canceled": 0}
            total = 0
            for status, cnt in rows.all():
                counts[str(status)] = int(cnt)
                total += int(cnt)
            counts["total"] = total
            return counts

    async def set_allowed_accounts(self, job_id: int, ids: Optional[Sequence[int]]):
        async with async_session() as session:
            job = await session.get(AddJob, job_id)
            if not job:
                return
            job.allowed_account_ids = self._fmt_ids(ids)
            job.updated_at = datetime.utcnow()
            await session.commit()

    async def cancel_jobs(self, ids: Sequence[int]) -> int:
        """Set status to 'canceled' for provided job ids if they are queued or in_progress.
        Returns number of jobs updated."""
        if not ids:
            return 0
        from sqlmodel import update

        async with async_session() as session:
            stmt = (
                update(AddJob)
                .where(AddJob.id.in_(list(ids)))
                .where(AddJob.status.in_(["queued", "in_progress"]))
                .values(status="canceled", updated_at=datetime.utcnow())
            )
            res = await session.exec(stmt)
            await session.commit()
            # res.rowcount may be None on some drivers; best-effort count
            try:
                return int(res.rowcount or 0)
            except Exception:
                return 0

    async def cancel_all(self) -> int:
        """Cancel all jobs that are queued or in_progress."""
        from sqlmodel import update

        async with async_session() as session:
            stmt = (
                update(AddJob)
                .where(AddJob.status.in_(["queued", "in_progress"]))
                .values(status="canceled", updated_at=datetime.utcnow())
            )
            res = await session.exec(stmt)
            await session.commit()
            try:
                return int(res.rowcount or 0)
            except Exception:
                return 0
