import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials

from app.core.config import settings

basic = HTTPBasic()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_admin(request: Request, creds: HTTPBasicCredentials = Depends(basic)):  # noqa: B008 - FastAPI DI
    # Session-based login
    if request.session.get("admin") is True:
        return True
    if not settings.ADMIN_USERNAME or not settings.ADMIN_PASSWORD:
        # no auth configured – allow, but this is insecure
        return True
    correct_user = secrets.compare_digest(creds.username, settings.ADMIN_USERNAME)
    correct_pass = secrets.compare_digest(creds.password, settings.ADMIN_PASSWORD)
    if not (correct_user and correct_pass):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    return True


def require_api_key(key: str | None = Depends(api_key_header)):
    if not settings.API_KEY:
        return True
    if not key or not secrets.compare_digest(key, settings.API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return True
