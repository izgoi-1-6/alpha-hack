"""Officer routes under /api/v1/officer/applications (CREDIT_OFFICER only: clients get 403 OFFICER_REQUIRED).

Reads apply lazy expiry. Stateful commands follow applications.commands.run_command: company then application row
locks (the order customer commands use), lazy expiry, idempotency replay, then the command's own checks; only a
successful result is stored for replay.
"""
from collections.abc import Callable
from datetime import datetime
from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from ..idempotency import IdempotencyKey
from ..identity import Db, Now, OfficerUser
from ..models import Company, User
from ..schemas import StrictModel, VersionInput
from ..applications import commands
from ..applications.lifecycle import get_application, lock_application
from ..applications.models import Application
from ..applications.schemas import StatusFilter
from ..documents import service as documents
from . import service, views
from .schemas import ApproveInput, AssigneeFilter, PreapproveInput, RejectInput, RequestInfoInput, ReviewInput

router = APIRouter(prefix='/officer/applications', tags=['officer'])


@router.get('')
def review_queue(user: OfficerUser, db: Db, now: Now, status: StatusFilter | None = None,
                 assignee: AssigneeFilter | None = None, company_id: str | None = None):
    rows = service.review_queue(db, user.id, now, status=status, assignee=assignee, company_id=company_id)
    return {'items': [views.staff_application(db, row, user.id) for row in rows], 'total': len(rows)}


@router.get('/{application_id}')
def read_application(application_id: str, user: OfficerUser, db: Db, now: Now):
    return views.staff_detail(db, get_application(db, application_id, now), user.id)


def run_command(application_id: str, data: StrictModel, request: Request, user: User, db: Session, now: datetime, key: str,
                apply: Callable[[Application, Company], None]):
    return commands.run_command(
        db, request, user.id, key, data, now, lock=lambda: lock_application(db, application_id, now), apply=apply,
        render=lambda application, company: {'application': views.staff_application(db, application, user.id, company)})


@router.post('/{application_id}/claim')
def claim(application_id: str, data: VersionInput, request: Request, user: OfficerUser, db: Db, now: Now,
          idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.claim(db, application, user, data, now))


@router.post('/{application_id}/request-info')
def request_info(application_id: str, data: RequestInfoInput, request: Request, user: OfficerUser, db: Db, now: Now,
                 idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.request_info(db, application, user, data, now))


@router.post('/{application_id}/preapprove')
def preapprove(application_id: str, data: PreapproveInput, request: Request, user: OfficerUser, db: Db, now: Now,
               idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.preapprove(db, application, company, user, data, now))


@router.post('/{application_id}/reject')
def reject(application_id: str, data: RejectInput, request: Request, user: OfficerUser, db: Db, now: Now,
           idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.reject(db, application, user, data, now))


@router.post('/{application_id}/documents/{document_id}/review')
def review_document(application_id: str, document_id: str, data: ReviewInput, request: Request, user: OfficerUser, db: Db,
                    now: Now, idempotency_key: IdempotencyKey):
    found = {}

    def lock():  # the document must belong to the application before the replay check
        locked = lock_application(db, application_id, now)
        found['document'] = documents.find_document(db, application_id, document_id, for_update=True)
        return locked

    return commands.run_command(
        db, request, user.id, idempotency_key, data, now, lock=lock,
        apply=lambda application, _company: service.review_document(db, application, user, found['document'], data, now),
        render=lambda application, company: {'document': views.staff_document(db, found['document']),
                                             'application': views.staff_application(db, application, user.id, company)})


@router.post('/{application_id}/approve')
def approve(application_id: str, data: ApproveInput, request: Request, user: OfficerUser, db: Db, now: Now,
            idempotency_key: IdempotencyKey):
    return run_command(application_id, data, request, user, db, now, idempotency_key,
                       lambda application, company: service.approve(db, application, user, data, now))
