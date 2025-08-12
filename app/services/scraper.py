import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    ChannelParticipantsAdmins,
    UserStatusEmpty,
    UserStatusLastMonth,
    UserStatusLastWeek,
    UserStatusOffline,
    UserStatusOnline,
    UserStatusRecently,
)


def _is_recent(status, min_recency: Optional[timedelta]) -> bool:
    if not min_recency:
        return True
    now = datetime.utcnow()
    if isinstance(status, UserStatusOnline):
        return True
    if isinstance(status, UserStatusRecently):
        return True
    if isinstance(status, UserStatusLastWeek):
        return min_recency <= timedelta(days=7)
    if isinstance(status, UserStatusLastMonth):
        return min_recency <= timedelta(days=30)
    if isinstance(status, UserStatusOffline):
        if status.was_online:
            return now - status.was_online <= min_recency
        return False
    return False


class Scraper:
    def __init__(self, client: TelegramClient):
        self.client = client

    async def scrape_usernames(
        self,
        source: str,
        limit: int = 1000,
        query: str = "",
        min_last_seen: Optional[timedelta] = None,
        skip_bots: bool = True,
        skip_admins: bool = True,
    ) -> List[str]:
        usernames: List[str] = []
        try:
            entity = await self.client.get_entity(source)
            participants = await self.client.get_participants(entity, search=query, limit=limit)
            # Optionally fetch admins to exclude
            admin_user_ids = set()
            if skip_admins:
                try:
                    admins = await self.client.get_participants(
                        entity, filter=type("AdminsFilter", (), {"__class__": object})()
                    )
                except Exception as e:  # noqa: BLE001
                    logging.getLogger(__name__).debug("admins fetch failed: %s", e)
                    admins = []
                for a in admins:
                    admin_user_ids.add(a.id)
            for u in participants:
                if skip_bots and getattr(u, "bot", False):
                    continue
                if skip_admins and u.id in admin_user_ids:
                    continue
                if not _is_recent(getattr(u, "status", None), min_last_seen):
                    continue
                if u.username:
                    usernames.append(u.username)
        except FloodWaitError as e:
            await asyncio.sleep(int(getattr(e, "seconds", 60)))
        # de-dup while preserving order
        seen = set()
        out: List[str] = []
        for name in usernames:
            if name not in seen:
                out.append(name)
                seen.add(name)
        return out

    @staticmethod
    def _status_info(status) -> Dict[str, Any]:
        now = datetime.utcnow()
        info = {"status": "unknown", "last_seen": None}
        if isinstance(status, UserStatusOnline):
            info["status"] = "online"
            info["last_seen"] = now
        elif isinstance(status, UserStatusRecently):
            info["status"] = "recently"
        elif isinstance(status, UserStatusLastWeek):
            info["status"] = "last_week"
        elif isinstance(status, UserStatusLastMonth):
            info["status"] = "last_month"
        elif isinstance(status, UserStatusOffline):
            info["status"] = "offline"
            if status.was_online:
                info["last_seen"] = status.was_online
        elif isinstance(status, UserStatusEmpty):
            info["status"] = "hidden"
        return info

    async def scrape_members_detailed(
        self,
        source: str,
        limit: int = 1000,
        query: str = "",
        min_last_seen: Optional[timedelta] = None,
        skip_bots: bool = True,
        skip_admins: bool = True,
        include_full: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Returns a list of dicts with as many fields as Telegram exposes to this account.
        Note: Phone numbers are only available when the user's privacy allows it (often not).
        """
        try:
            entity = await self.client.get_entity(source)
        except Exception:
            return []
        # Pre-load admins to optionally skip
        admin_user_ids = set()
        if skip_admins:
            try:
                admins = await self.client.get_participants(entity, filter=ChannelParticipantsAdmins())
                for a in admins:
                    admin_user_ids.add(a.id)
            except Exception as e:  # noqa: BLE001
                logging.getLogger(__name__).debug("admins preload failed: %s", e)
        # Fetch participants
        participants = await self.client.get_participants(entity, search=query, limit=limit)
        seen_ids = set()
        rows: List[Dict[str, Any]] = []
        for u in participants:
            if u.id in seen_ids:
                continue
            seen_ids.add(u.id)
            if skip_bots and getattr(u, "bot", False):
                continue
            if skip_admins and u.id in admin_user_ids:
                continue
            if not _is_recent(getattr(u, "status", None), min_last_seen):
                continue
            st = self._status_info(getattr(u, "status", None))
            rec: Dict[str, Any] = {
                "id": u.id,
                "username": (u.username or "") if hasattr(u, "username") else "",
                "phone": (u.phone or "") if hasattr(u, "phone") and u.phone else "",
                "first_name": getattr(u, "first_name", "") or "",
                "last_name": getattr(u, "last_name", "") or "",
                "full_name": (
                    f"{(getattr(u,'first_name','') or '').strip()} {(getattr(u,'last_name','') or '').strip()}"
                ).strip(),
                "is_bot": bool(getattr(u, "bot", False)),
                "is_verified": bool(getattr(u, "verified", False)),
                "is_premium": bool(getattr(u, "premium", False)),
                "is_restricted": bool(getattr(u, "restricted", False)),
                "lang_code": getattr(u, "lang_code", None) or "",
                "status": st["status"],
                "last_seen": st["last_seen"].isoformat() if st["last_seen"] else "",
                "about": "",
                "common_chats_count": None,
            }
            if include_full:
                try:
                    fu = await self.client(GetFullUserRequest(id=u))
                    full = getattr(fu, "full_user", None)
                    if full is not None:
                        rec["about"] = getattr(full, "about", "") or ""
                        rec["common_chats_count"] = getattr(full, "common_chats_count", None)
                except FloodWaitError as e:
                    await asyncio.sleep(int(getattr(e, "seconds", 30)))
                except Exception as e:  # noqa: BLE001
                    logging.getLogger(__name__).debug("full user fetch failed: %s", e)
            rows.append(rec)
        return rows
