from datetime import datetime
from typing import Optional

from sqlmodel import select

from app.core.db import async_session
from app.models.db import AppControl


class AppControlService:
    async def get(self, key: str) -> Optional[str]:
        async with async_session() as session:
            res = await session.execute(select(AppControl).where(AppControl.key == key))
            row = res.scalars().first()
            return row.value if row else None

    async def set(self, key: str, value: str) -> None:
        async with async_session() as session:
            res = await session.execute(select(AppControl).where(AppControl.key == key))
            row = res.scalars().first()
            if not row:
                row = AppControl(key=key, value=value, updated_at=datetime.utcnow())
                session.add(row)
            else:
                row.value = value
                row.updated_at = datetime.utcnow()
            await session.commit()
