"""Officer commands on an application the router has locked (company row, then application row, lazy expiry) after
the idempotency replay check; any ApiError rolls the whole command back, so nothing is half-recorded.

Claim checks state, then another assignee, then the version (a racing claim that lost sees ALREADY_ASSIGNED). Every
decision checks the assignment, then the version, then the state, then its own guards, and records an
OfficerDecision with the reason and the latest evaluation, a StatusHistory row (actor, reason, revision) and its
simulated notification through the transition service. Statuses only change through ApplicationChange.move.
"""
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..clock import as_utc
from ..errors import ApiError
from ..models import Company, User
from ..schemas import VersionInput
from ..applications.info_requests import create_info_request
from ..applications.lifecycle import PREAPPROVAL_TTL, ApplicationChange, expire_if_due, preapproval_notice
from ..applications.models import Application, OfficerDecision
from ..applications.products import application_product
from ..applications.service import require_version
from ..applications.views import latest_evaluation
from .policy import CLAIMABLE, REJECT_PHASE, amount_error_message, preapproval_terms
from .schemas import PreapproveInput, RejectInput, RequestInfoInput

INFO_REQUEST_NOTICE = 'Кредитный специалист запросил дополнительные сведения. Откройте заявку и ответьте на вопрос.'
REJECTION_NOTICE = 'По заявке принят отказ кредитного специалиста. Причина указана в истории заявки.'
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)


def review_queue(db: Session, officer_id: str, now: datetime, *, status: str | None = None, assignee: str | None = None,
                 company_id: str | None = None) -> list[Application]:
    """Applications for review in arrival order (submitted_at, then id; never-submitted rows last). Lazy expiry runs
    before the status filter. Drafts are listed only when status=DRAFT is asked for."""
    query = select(Application)
    if company_id is not None:
        query = query.where(Application.company_id == company_id)
    if assignee == 'me':
        query = query.where(Application.assignee_id == officer_id)
    elif assignee == 'unassigned':
        query = query.where(Application.assignee_id.is_(None))
    rows = db.scalars(query).all()
    for row in rows:
        expire_if_due(db, row, now)
    rows = [row for row in rows if row.status == status] if status else [row for row in rows if row.status != 'DRAFT']
    return sorted(rows, key=lambda row: (row.submitted_at is None, as_utc(row.submitted_at) if row.submitted_at else EARLIEST, row.id))


def require_assignee(application: Application, officer: User) -> None:
    if application.assignee_id != officer.id:
        raise ApiError(409, 'ASSIGNMENT_REQUIRED', 'Решение принимает специалист, который взял заявку в работу.')


def invalid_status(message: str) -> ApiError:
    return ApiError(409, 'INVALID_STATUS', message)


def claim(db: Session, application: Application, officer: User, data: VersionInput, now: datetime) -> None:
    """Assigns an unassigned case to the session officer: one version increment, no status transition, no history
    and no OfficerDecision. The current assignee's claim is a no-op success; there is no reassignment."""
    if application.status not in CLAIMABLE:
        raise invalid_status('Взять в работу можно заявку на рассмотрении, в ожидании сведений или на этапе документов.')
    if application.assignee_id not in (None, officer.id):
        raise ApiError(409, 'ALREADY_ASSIGNED', 'Заявку уже взял в работу другой специалист.')
    require_version(application, data.version)
    if application.assignee_id == officer.id:
        return
    application.assignee_id = officer.id
    ApplicationChange(db, application, actor_id=officer.id, now=now).touch()


def record_decision(db: Session, application: Application, officer: User, *, phase: str, action: str, reason: str,
                    now: datetime, amount_rub: int | None = None) -> OfficerDecision:
    evaluation = latest_evaluation(db, application.id)
    sequence = (db.scalar(select(func.max(OfficerDecision.sequence)).where(OfficerDecision.application_id == application.id)) or 0) + 1
    row = OfficerDecision(application_id=application.id, sequence=sequence, officer_id=officer.id, phase=phase, action=action,
                          amount_rub=amount_rub, reason=reason, evaluation_id=None if evaluation is None else evaluation.id,
                          created_at=now)
    db.add(row)
    db.flush()
    return row


def require_review(application: Application, message: str) -> None:
    if application.status != 'MANUAL_REVIEW':
        raise invalid_status(message)


def request_info(db: Session, application: Application, officer: User, data: RequestInfoInput, now: datetime) -> None:
    """MANUAL_REVIEW → NEED_INFO: an officer client_answers request (the reason is its question), its decision row."""
    require_assignee(application, officer)
    require_version(application, data.version)
    require_review(application, 'Запросить сведения можно у заявки на рассмотрении.')
    create_info_request(db, application, kind='client_answers', source=None, requested_fields=data.requested_fields,
                        question=data.reason, now=now, officer_id=officer.id)
    record_decision(db, application, officer, phase='preliminary', action='request_info', reason=data.reason, now=now)
    ApplicationChange(db, application, actor_id=officer.id, now=now).move(
        'NEED_INFO', reason_code='INFO_REQUESTED', reason_text=data.reason, notification=INFO_REQUEST_NOTICE)


def preapprove(db: Session, application: Application, company: Company, officer: User, data: PreapproveInput, now: datetime) -> None:
    """MANUAL_REVIEW → PREAPPROVED (R12) at an amount within product minimum..min(request, scored limit), unless a
    mandatory stop or a noncomputable limit refuses it. The 14-day document deadline starts now."""
    require_assignee(application, officer)
    require_version(application, data.version)
    require_review(application, 'Предварительно одобрить можно заявку на рассмотрении.')
    bounds, refusal = preapproval_terms(application, company, latest_evaluation(db, application.id), application_product(application))
    if refusal:
        raise ApiError(409, *refusal)
    low, high = bounds
    if not low <= data.amount_rub <= high:
        raise ApiError(422, 'AMOUNT_OUT_OF_BOUNDS', amount_error_message(low, high),
                       fields={'amount_rub': amount_error_message(low, high)}, details={'amount_min_rub': low, 'amount_max_rub': high})
    application.preapproved_amount_rub = data.amount_rub
    application.preapproved_at = now
    application.preapproval_expires_at = now + PREAPPROVAL_TTL
    record_decision(db, application, officer, phase='preliminary', action='preapprove', reason=data.reason, now=now,
                    amount_rub=data.amount_rub)
    ApplicationChange(db, application, actor_id=officer.id, now=now).move(
        'PREAPPROVED', reason_code='R12', reason_text=data.reason, notification=preapproval_notice(application, by_officer=True))


def reject(db: Session, application: Application, officer: User, data: RejectInput, now: datetime) -> None:
    """MANUAL_REVIEW → REJECTED (preliminary, R12) or PREAPPROVED/DOCS_UPLOADED/DOCS_REWORK → REJECTED (final), with
    no document prerequisite."""
    require_assignee(application, officer)
    require_version(application, data.version)
    phase = REJECT_PHASE.get(application.status)
    if phase is None:
        raise invalid_status('Отказать можно на рассмотрении или на этапе документов.')
    record_decision(db, application, officer, phase=phase, action='reject', reason=data.reason, now=now)
    ApplicationChange(db, application, actor_id=officer.id, now=now).move(
        'REJECTED', reason_code='R12' if phase == 'preliminary' else 'FINAL_REJECTED', reason_text=data.reason,
        notification=REJECTION_NOTICE)
