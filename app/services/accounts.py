from typing import List, Optional
from datetime import datetime, timedelta
from sqlmodel import select
from app.models.db import Account
from app.core.db import async_session

class AccountService:
    async def get(self, account_id: int) -> Optional[Account]:
        async with async_session() as session:
            return await session.get(Account, account_id)
    async def create(self, phone: str, session_path: str, proxy: Optional[str] = None, device_string: Optional[str] = None) -> Account:
        async with async_session() as session:
            acc = Account(phone=phone, session_path=session_path, proxy=proxy, device_string=device_string)
            session.add(acc)
            await session.commit()
            await session.refresh(acc)
            return acc

    async def list(self) -> List[Account]:
        async with async_session() as session:
            res = await session.execute(select(Account))
            return list(res.scalars().all())

    async def available_accounts(self) -> List[Account]:
        now = datetime.utcnow()
        async with async_session() as session:
            res = await session.execute(select(Account))
            out = []
            for a in res.scalars().all():
                if not a.cooldown_until or a.cooldown_until <= now:
                    out.append(a)
            return out

    async def set_cooldown(self, account_id: int, seconds: int, last_error: Optional[str] = None):
        async with async_session() as session:
            acc = await session.get(Account, account_id)
            if not acc:
                return
            acc.cooldown_until = datetime.utcnow().replace(microsecond=0) if seconds == 0 else datetime.utcnow() + timedelta(seconds=seconds)
            acc.last_error = last_error
            await session.commit()

    async def delete(self, account_id: int) -> bool:
        async with async_session() as session:
            acc = await session.get(Account, account_id)
            if not acc:
                return False
            await session.delete(acc)
            await session.commit()
            return True
