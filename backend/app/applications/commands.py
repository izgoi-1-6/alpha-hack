"""The guarded sequence every stateful application command follows, for customer and officer routes alike.

Authentication and role run as route dependencies first. Then: load and lock the application (company row, then
application row, then lazy expiry), idempotency replay, the committed expiry refusal, the command's own version/state
validation and work, and `remember` of the 2xx body. Any ApiError rolls the whole command back.
"""
from collections.abc import Callable
from datetime import datetime
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from .. import idempotency
from ..errors import error_response
from ..models import Company
from ..schemas import StrictModel
from .models import Application


def expired_response() -> JSONResponse:
    """A committed refusal: the expiry this request recorded stays persisted."""
    return error_response(409, 'APPLICATION_EXPIRED', 'Срок предварительного одобрения истёк. Для продолжения создайте новую заявку.')


def run_command(db: Session, request: Request, actor_id: str, key: str, data: StrictModel, now: datetime, *,
                lock: Callable[[], tuple[Application, Company, bool]], apply: Callable[[Application, Company], None],
                render: Callable[[Application, Company], dict]):
    application, company, expired = lock()
    scope = idempotency.scope_of(request, actor_id, key, data)
    replayed = idempotency.replay(db, scope)
    if replayed is not None:
        return replayed
    if expired:
        return expired_response()
    apply(application, company)
    return idempotency.remember(db, scope, render(application, company), now=now, resource_id=application.id)
