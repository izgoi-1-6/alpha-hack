from collections.abc import Callable
from datetime import datetime, timezone
from fastapi import Request

def utc_now() -> datetime:
    """FastAPI-overridable UTC clock. Never use the fixture business date for sessions."""
    return datetime.now(timezone.utc)

def request_clock(request: Request) -> Callable[[], datetime]:
    """The request's clock as a callable, for a time read later in the request than the `Now` dependency (an upload
    applies its command once its body has arrived); it honours a test override of utc_now."""
    return request.app.dependency_overrides.get(utc_now, utc_now)

def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def iso_utc(value: datetime) -> str:
    return as_utc(value).isoformat().replace('+00:00', 'Z')
