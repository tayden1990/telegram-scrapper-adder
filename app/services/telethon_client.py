import os
from typing import Optional

from telethon import TelegramClient
from telethon.network.connection import ConnectionTcpAbridged
from telethon.sessions import StringSession


def parse_proxy(proxy_str: Optional[str]) -> Optional[tuple[str, int, str, Optional[str]]]:
    # Expect formats: socks5://user:pass@host:port or http://host:port
    if not proxy_str:
        return None
    try:
        from urllib.parse import urlparse

        u = urlparse(proxy_str)
        host = u.hostname
        port = u.port or 0
        scheme = u.scheme
        username = u.username or ""
        password = u.password
        if not host or not port:
            return None
        # Telethon expects (type, host, port, rdns, username, password)
        if scheme.startswith("socks"):
            import socks

            return (socks.SOCKS5, host, int(port), True, username or None, password)
        if scheme.startswith("http"):
            import socks

            return (socks.HTTP, host, int(port), True, username or None, password)
    except Exception:
        return None
    return None


class ClientFactory:
    def __init__(self, api_id: int, api_hash: str, sessions_dir: str = "./sessions"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.sessions_dir = sessions_dir
        os.makedirs(self.sessions_dir, exist_ok=True)

    def build(
        self, session_name: str, proxy: Optional[tuple] = None, device_string: Optional[str] = None
    ) -> TelegramClient:
        # Allow either a plain name (relative to sessions_dir) or a full/relative path
        if os.path.isabs(session_name) or os.sep in session_name:
            session_path = session_name
        else:
            session_path = os.path.join(self.sessions_dir, session_name)
        kwargs = {
            "session": session_path,
            "api_id": self.api_id,
            "api_hash": self.api_hash,
            "connection": ConnectionTcpAbridged,
            "proxy": proxy,
            "flood_sleep_threshold": 120,
            # harden connectivity
            "request_retries": 8,
            "connection_retries": 5,
            "retry_delay": 2,
            "use_ipv6": False,
        }
        if device_string:
            kwargs.update(device_model=device_string)
        client = TelegramClient(**kwargs)
        return client

    def build_from_string(self, string_session: str, proxy: Optional[tuple] = None) -> TelegramClient:
        return TelegramClient(StringSession(string_session), self.api_id, self.api_hash, proxy=proxy)
