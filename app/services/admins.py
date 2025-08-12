from typing import Optional

from passlib.context import CryptContext
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.db import async_session
from app.models.db import AdminUser

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


class AdminService:
    async def get_by_username(self, username: str) -> Optional[AdminUser]:
        async with async_session() as session:
            res = await session.execute(
                select(AdminUser).where(
                    AdminUser.username == username,
                    AdminUser.is_active.is_(True),
                )
            )
            return res.scalars().first()

    async def _get_any_by_username(self, username: str) -> Optional[AdminUser]:
        """Fetch by username regardless of is_active to detect duplicates."""
        async with async_session() as session:
            res = await session.execute(select(AdminUser).where(AdminUser.username == username))
            return res.scalars().first()

    async def create(self, username: str, password: str) -> AdminUser:
        # Proactively check to avoid IntegrityError and return a clear message
        existing = await self._get_any_by_username(username)
        if existing is not None:
            raise ValueError(f"admin user '{username}' already exists")
        async with async_session() as session:
            user = AdminUser(username=username, password_hash=hash_password(password), is_active=True)
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                # Race condition fallback
                await session.rollback()
                raise ValueError(f"admin user '{username}' already exists") from None
            await session.refresh(user)
            return user

    async def list(self) -> list[AdminUser]:
        async with async_session() as session:
            res = await session.execute(select(AdminUser))
            return list(res.scalars().all())

    async def deactivate(self, username: str, active: bool = False) -> bool:
        async with async_session() as session:
            res = await session.execute(select(AdminUser).where(AdminUser.username == username))
            user = res.scalars().first()
            if not user:
                return False
            user.is_active = active
            await session.commit()
            return True

    async def change_password(self, username: str, new_password: str) -> bool:
        async with async_session() as session:
            res = await session.execute(select(AdminUser).where(AdminUser.username == username))
            user = res.scalars().first()
            if not user:
                return False
            user.password_hash = hash_password(new_password)
            await session.commit()
            return True
