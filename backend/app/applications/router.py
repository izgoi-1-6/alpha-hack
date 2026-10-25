"""Customer application routes under /api/v1/applications (CLIENT only; officers get 403, other clients 404).

Stateful POST commands follow commands.run_command: ownership, company then application row locks, lazy expiry,
idempotency replay, then the command's own version/state validation; only a successful result is stored for replay.
"""
from collections.abc import Callable
from datetime import datetime
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from .. import idempotency
from ..companies import get_owned_company
from ..idempotency import IdempotencyKey
from ..identity import ClientUser, Db, Now
from ..models import Company, User
from ..schemas import StrictModel, VersionInput
from . import commands, service, views
from .lifecycle import get_owned_application, lock_owned_application, owned_applications
from .models import Application
from .schemas import AnswersPatch, CancelInput, CreateInput, StatusFilter, SubmitInput

router = APIRouter(prefix='/applications', tags=['applications'])


def run_command(application_id: str, data: StrictModel, request: Request, user: User, db: Session, now: datetime, key: str,
                apply: Callable[[Application, Company], None]):
    return commands.run_command(
        db, request, user.id, key, data, now, lock=lambda: lock_owned_application(db, application_id, user.id, now),
        apply=apply, render=lambda application, company: {'application': views.public_application(db, application, company)})


@router.post('', status_code=201)
def create_application(data: CreateInput, request: Request, user: ClientUser, db: Db, now: Now, idempotency_key: IdempotencyKey):
    company = get_owned_company(db, data.company_id, user.id, for_update=True)
    scope = idempotency.scope_of(request, user.id, idempotency_key, data)
    replayed = idempotency.replay(db, scope)
    if replayed is not None:
        return replayed
    application = service.create_application(db, company, user.id, data, now)
    return idempotency.remember(db, scope, {'application': views.public_application(db, application, company)},
                                now=now, status=201, resource_id=application.id)


@router.get('')
def list_applications(user: ClientUser, db: Db, now: Now, status: StatusFilter | None = None, company_id: str | None = None):
    rows = owned_applications(db, user.id, now, status=status, company_id=company_id)
    return {'items': [views.public_application(db, row) for row in rows], 'total': len(rows)}


@router.get('/{application_id}')
def read_application(application_id: str, user: ClientUser, db: Db, now: Now):
    return {'application': views.public_application(db, get_owned_application(db, application_id, user.id, now))}


@router.get('/{application_id}/dialog')
def read_dialog(application_id: str, user: ClientUser, db: Db, now: Now):
    return views.dialog(db, get_owned_application(db, application_id, user.id, now))


@router.get('/{application_id}/history')
def read_history(application_id: str, user: ClientUser, db: Db, now: Now):
    items = views.public_history(db, get_owned_application(db, application_id, user.id, now))
    return {'items': items, 'total': len(items)}


@router.patch('/{application_id}/answers')
def save_answers(application_id: str, data: AnswersPatch, user: ClientUser, db: Db, now: Now):
    application, company, expired = lock_owned_application(db, application_id, user.id, now)
    if expired:
        return commands.expired_response()
    service.save_answers(db, application, user.id, data, now)
    return {'application': views.public_application(db, application, company)}


@router.post('/{application_id}/submit')
def submit_application(application_id: str, data: SubmitInput, request: Request, user: ClientUser, db: Db, now: Now,
                       idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.submit_application(db, application, company, user.id, data, now))


@router.post('/{application_id}/retry-check')
def retry_check(application_id: str, data: VersionInput, request: Request, user: ClientUser, db: Db, now: Now,
                idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.retry_check(db, application, company, user.id, data.version, now))


@router.post('/{application_id}/cancel')
def cancel_application(application_id: str, data: CancelInput, request: Request, user: ClientUser, db: Db, now: Now,
                       idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.cancel_application(db, application, user.id, data, now))
