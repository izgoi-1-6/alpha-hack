"""Idempotent stateful POST commands.

Scope is (actor, method, path, Idempotency-Key) plus a SHA-256 digest of the canonical JSON body. Callers check
ownership and lock the resource row first, `replay` before any version or state validation, apply the command and
`remember` the successful result in the same transaction. Failed commands roll back and are never stored, so they
may be retried with the same key.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Annotated
from fastapi import Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from .errors import ApiError
from .models import IdempotencyRecord

IdempotencyKey = Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=128)]


@dataclass(frozen=True)
class Scope:
    actor_id: str
    method: str
    path: str
    key: str
    digest: str


def scope_of(request: Request, actor_id: str, key: str, body: BaseModel) -> Scope:
    canonical = json.dumps(body.model_dump(mode='json'), sort_keys=True, separators=(',', ':'))
    return Scope(actor_id, request.method, request.url.path, key, hashlib.sha256(canonical.encode()).hexdigest())


def replay(db: Session, scope: Scope) -> JSONResponse | None:
    """The stored response of an exact replay, or None for a new key; 409 when the key was used with another body."""
    record = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.actor_id == scope.actor_id, IdempotencyRecord.method == scope.method,
        IdempotencyRecord.path == scope.path, IdempotencyRecord.key == scope.key))
    if record is None:
        return None
    if record.request_hash != scope.digest:
        raise ApiError(409, 'IDEMPOTENCY_CONFLICT', 'Ключ уже использован с другими данными')
    return JSONResponse(record.response_body, status_code=record.response_status)


def remember(db: Session, scope: Scope, body: dict, *, now: datetime, status: int = 200, resource_id: str | None = None) -> dict:
    """Stores a successful result for later replays and returns it unchanged."""
    db.add(IdempotencyRecord(actor_id=scope.actor_id, method=scope.method, path=scope.path, key=scope.key,
                             request_hash=scope.digest, response_status=status, response_body=body,
                             resource_id=resource_id, created_at=now))
    db.flush()
    return body
