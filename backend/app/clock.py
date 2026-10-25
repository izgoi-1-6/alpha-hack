from collections.abc import Callable
from datetime import datetime, timezone

def utc_now() -> datetime:
    """FastAPI-overridable UTC clock. Never use the fixture business date for sessions."""
    return datetime.now(timezone.utc)

def get_clock() -> Callable[[], datetime]:
    """FastAPI dependency: the clock itself, for a time read later in the request than `Now` (an upload applies its
    command once its body has arrived). Tests override it with their clock, as they override utc_now."""
    return utc_now

def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def iso_utc(value: datetime) -> str:
    return as_utc(value).isoformat().replace('+00:00', 'Z')
