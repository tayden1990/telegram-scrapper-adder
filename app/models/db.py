from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone: str
    session_path: str
    proxy: Optional[str] = None
    device_string: Optional[str] = None
    cooldown_until: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Member(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    username: Optional[str] = None
    access_hash: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    last_seen: Optional[str] = None
    source: Optional[str] = None  # group username/id scraped from
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AddJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    dest_group: str
    username: Optional[str] = None
    phone: Optional[str] = None
    member_user_id: int = 0
    status: str = "queued"  # queued | in_progress | success | failed | skipped
    kind: str = "add"       # add | message
    allowed_account_ids: Optional[str] = None  # comma-separated ids
    batch_id: Optional[str] = None
    message_text: Optional[str] = None
    attempt: int = 0
    error: Optional[str] = None
    account_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    next_attempt_at: Optional[datetime] = None

class AppControl(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class AdminUser(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str
    password_hash: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
