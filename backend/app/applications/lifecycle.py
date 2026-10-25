"""The only place an application's status changes, plus the owner load helpers that apply lazy expiry.

`ApplicationChange` validates each move against TRANSITIONS, increments the version once per command (however many
moves it records), and appends a StatusHistory row with its simulated in-app Notification. There is no arbitrary
status update. Officer and document commands (Tasks 5 and 6) use the same class.
"""
from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..clock import as_utc
from ..companies import get_owned_company
from ..errors import ApiError
from ..models import Company
from .models import Application, Notification, StatusHistory

TRANSITIONS: dict[str, frozenset[str]] = {
    'DRAFT': frozenset({'CHECKING', 'CANCELLED'}),
    'CHECKING': frozenset({'WAIT_EXTERNAL', 'NEED_INFO', 'MANUAL_REVIEW', 'PREAPPROVED', 'REJECTED'}),
    'WAIT_EXTERNAL': frozenset({'CHECKING', 'CANCELLED'}),
    'NEED_INFO': frozenset({'CHECKING', 'MANUAL_REVIEW', 'CANCELLED'}),
    'MANUAL_REVIEW': frozenset({'NEED_INFO', 'PREAPPROVED', 'REJECTED', 'CANCELLED'}),
    'PREAPPROVED': frozenset({'DOCS_UPLOADED', 'REJECTED', 'CANCELLED', 'EXPIRED'}),
    'DOCS_UPLOADED': frozenset({'DOCS_REWORK', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED'}),
    'DOCS_REWORK': frozenset({'DOCS_UPLOADED', 'REJECTED', 'CANCELLED', 'EXPIRED'}),
    'APPROVED': frozenset(), 'REJECTED': frozenset(), 'CANCELLED': frozenset(), 'EXPIRED': frozenset(),
}
EXPIRING = frozenset({'PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK'})
PREAPPROVAL_TTL = timedelta(days=14)
# Default simulated in-app message per resulting status; a move may pass a more specific one.
NOTIFICATIONS = {
    'DRAFT': 'Черновик заявки создан. Заполните анкету и отправьте её на проверку.',
    'CHECKING': 'Заявка проверяется: демо-источники и скоринг.',
    'WAIT_EXTERNAL': 'Демо-источник временно недоступен. Повторите проверку в заявке.',
    'NEED_INFO': 'Для продолжения нужны дополнительные сведения. Откройте заявку.',
    'MANUAL_REVIEW': 'Заявка передана кредитному специалисту на рассмотрение.',
    'PREAPPROVED': 'Заявка предварительно одобрена. Загрузите документы в течение 14 дней. Это не окончательное решение.',
    'DOCS_UPLOADED': 'Документы переданы на проверку.',
    'DOCS_REWORK': 'Часть документов нужно заменить. Откройте заявку.',
    'APPROVED': 'Заявка одобрена (демонстрационное решение). Деньги не перечисляются.',
    'REJECTED': 'По заявке принят отказ. Причина указана в заявке.',
    'CANCELLED': 'Заявка отменена.',
    'EXPIRED': 'Срок предварительного одобрения истёк. Для продолжения создайте новую заявку.',
}
CANCELLABLE = frozenset(status for status, targets in TRANSITIONS.items() if 'CANCELLED' in targets)


def record_history(db: Session, application: Application, from_status: str | None, *, actor_id: str | None,
                   reason_code: str, reason_text: str, now: datetime, notification: str | None = None) -> StatusHistory:
    """Appends the history row for the application's current status and its simulated notification."""
    sequence = (db.scalar(select(func.max(StatusHistory.sequence)).where(StatusHistory.application_id == application.id)) or 0) + 1
    row = StatusHistory(application_id=application.id, sequence=sequence, from_status=from_status, to_status=application.status,
                        actor_id=actor_id, reason_code=reason_code, reason_text=reason_text,
                        application_version=application.version, created_at=now)
    db.add(row)
    db.flush()
    db.add(Notification(application_id=application.id, status_history_id=row.id, event_code=f'application_{application.status.lower()}',
                        channel='demo_in_app', message=notification or NOTIFICATIONS[application.status], created_at=now))
    db.flush()
    return row


def record_creation(db: Session, application: Application, *, actor_id: str, now: datetime) -> StatusHistory:
    return record_history(db, application, None, actor_id=actor_id, reason_code='CREATED',
                          reason_text='Черновик создан из сохранённой предварительной оценки.', now=now)


class ApplicationChange:
    """The changes one command makes to a locked application.

    `touch()` is a same-state edit (answers, a claim): one version increment, no history. `move()` validates the
    transition, increments the version if this command has not yet, and records history plus notification with the
    resulting revision. Several moves in one command (DRAFT→CHECKING→outcome) share that single increment.
    `by_system=True` records a move the system made within the command (an automated check result: actor null)."""

    def __init__(self, db: Session, application: Application, *, actor_id: str | None, now: datetime):
        self.db, self.application, self.actor_id, self.now = db, application, actor_id, now
        self.bumped = False

    def touch(self) -> None:
        if not self.bumped:
            self.application.version += 1
            self.bumped = True
        self.application.updated_at = self.now

    def move(self, to_status: str, *, reason_code: str, reason_text: str, notification: str | None = None,
             by_system: bool = False) -> StatusHistory:
        application = self.application
        if to_status not in TRANSITIONS[application.status]:
            raise ApiError(409, 'INVALID_STATUS', 'Действие недоступно в текущем статусе заявки.')
        self.touch()
        from_status, application.status = application.status, to_status
        return record_history(self.db, application, from_status, actor_id=None if by_system else self.actor_id,
                              reason_code=reason_code, reason_text=reason_text, now=self.now, notification=notification)


def expire_if_due(db: Session, application: Application, now: datetime) -> bool:
    """Lazy expiry: PREAPPROVED/DOCS_UPLOADED/DOCS_REWORK become EXPIRED once now >= preapproval_expires_at
    (preapproved_at + 14 days). The row is re-read under a lock, so concurrent readers record exactly one expiry.
    Returns True when this call recorded it. Call right after loading, before other changes to the row."""
    deadline = application.preapproval_expires_at
    if application.status not in EXPIRING or deadline is None or now < as_utc(deadline):
        return False
    db.refresh(application, with_for_update=True)
    if application.status not in EXPIRING:
        return False
    ApplicationChange(db, application, actor_id=None, now=now).move(
        'EXPIRED', reason_code='PREAPPROVAL_EXPIRED', reason_text='Истёк срок предварительного одобрения (14 дней).')
    return True


def owned_query(user_id: str):
    return select(Application).join(Company, Company.id == Application.company_id).where(Company.owner_user_id == user_id)


def get_owned_application(db: Session, application_id: str, user_id: str, now: datetime) -> Application:
    """Owner read: 404 for an absent or another client's application; lazy expiry applied."""
    application = db.scalar(owned_query(user_id).where(Application.id == application_id))
    if application is None:
        raise ApiError(404, 'APPLICATION_NOT_FOUND', 'Заявка не найдена')
    expire_if_due(db, application, now)
    return application


def lock_owned_application(db: Session, application_id: str, user_id: str, now: datetime) -> tuple[Application, Company, bool]:
    """Owner command: locks the company row, then the application row (always in that order, so commands for one
    company serialize: duplicate-active checks, source recovery), then applies lazy expiry. Returns whether this call
    recorded an expiry, so the command can refuse while the expiry still commits."""
    company_id = db.scalar(select(Application.company_id).join(Company, Company.id == Application.company_id)
                           .where(Application.id == application_id, Company.owner_user_id == user_id))
    if company_id is None:
        raise ApiError(404, 'APPLICATION_NOT_FOUND', 'Заявка не найдена')
    company = get_owned_company(db, company_id, user_id, for_update=True)
    application = db.scalar(select(Application).where(Application.id == application_id).with_for_update()
                            .execution_options(populate_existing=True))
    return application, company, expire_if_due(db, application, now)


def owned_applications(db: Session, user_id: str, now: datetime, *, status: str | None = None, company_id: str | None = None) -> list[Application]:
    """The client's applications, newest first, after lazy expiry (so a status filter sees EXPIRED rows as such)."""
    query = owned_query(user_id)
    if company_id is not None:
        query = query.where(Application.company_id == company_id)
    rows = db.scalars(query.order_by(Application.created_at.desc(), Application.id.desc())).all()
    for row in rows:
        expire_if_due(db, row, now)
    return [row for row in rows if status is None or row.status == status]
