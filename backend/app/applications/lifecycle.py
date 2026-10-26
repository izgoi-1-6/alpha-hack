"""The only place an application's status changes, plus the owner load helpers that apply lazy expiry.

`ApplicationChange` validates each move against TRANSITIONS, increments the version once per command (however many
moves it records), and appends a StatusHistory row with its simulated in-app Notification. There is no arbitrary
status update. Officer and document commands use the same class.
"""
from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..clock import as_utc
from ..errors import ApiError
from ..models import Company
from ..recommendations.service import rub
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
    'CHECKING': 'Заявка проверяется по данным источников.',
    'WAIT_EXTERNAL': 'Источник данных временно недоступен. Повторите проверку в заявке.',
    'NEED_INFO': 'Для продолжения нужны дополнительные сведения. Откройте заявку.',
    'MANUAL_REVIEW': 'Заявка передана кредитному специалисту на рассмотрение.',
    'PREAPPROVED': 'Заявка предварительно одобрена. Загрузите документы в течение 14 дней. Это не окончательное решение.',
    'DOCS_UPLOADED': 'Документы переданы на проверку.',
    'DOCS_REWORK': 'Часть документов нужно заменить. Откройте заявку.',
    'APPROVED': 'Заявка одобрена. Деньги не перечисляются, договор не подписывается.',
    'REJECTED': 'По заявке принят отказ. Причина указана в заявке.',
    'CANCELLED': 'Заявка отменена.',
    'EXPIRED': 'Срок предварительного одобрения истёк. Для продолжения создайте новую заявку.',
}
CANCELLABLE = frozenset(status for status, targets in TRANSITIONS.items() if 'CANCELLED' in targets)


def preapproval_notice(application: Application, *, by_officer: bool = False) -> str:
    """The simulated message of a preliminary approval: the amount and the document deadline as a calendar date. The
    UTC date is never later than the customer's local date in Russia's time zones; the exact moment is in the
    application (`preapproval_expires_at`), so the message carries no raw timestamp."""
    subject = 'Кредитный специалист предварительно одобрил заявку' if by_officer else 'Заявка предварительно одобрена'
    return (f'{subject} на {rub(application.preapproved_amount_rub)}. Загрузите документы в течение 14 дней: срок истекает '
            f'{as_utc(application.preapproval_expires_at):%d.%m.%Y}, точное время указано в заявке. '
            'Это не окончательное решение.')


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


def scoped(query, owner_id: str | None):
    """Owner routes pass the session client's id (another client's application is then absent); staff routes, which
    are role-gated, pass None."""
    query = query.join(Company, Company.id == Application.company_id)
    return query if owner_id is None else query.where(Company.owner_user_id == owner_id)


def owned_query(user_id: str):
    return scoped(select(Application), user_id)


def not_found() -> ApiError:
    return ApiError(404, 'APPLICATION_NOT_FOUND', 'Заявка не найдена')


def get_application(db: Session, application_id: str, now: datetime, *, owner_id: str | None = None) -> Application:
    """A read: 404 for an absent application (or another client's, when owner-scoped); lazy expiry applied."""
    application = db.scalar(scoped(select(Application), owner_id).where(Application.id == application_id))
    if application is None:
        raise not_found()
    expire_if_due(db, application, now)
    return application


def require_application(db: Session, application_id: str, *, owner_id: str | None = None) -> None:
    """Existence and ownership only (404), with no lock and no lazy expiry: a document upload checks this before
    reading its body, and its command lock later records any expiry."""
    if db.scalar(scoped(select(Application.id), owner_id).where(Application.id == application_id)) is None:
        raise not_found()


def lock_application(db: Session, application_id: str, now: datetime, *, owner_id: str | None = None) -> tuple[Application, Company, bool]:
    """A command: locks the company row, then the application row (always in that order, for customer and officer
    commands alike, so commands for one company serialize: duplicate-active checks, source recovery, assignment and
    decisions), then applies lazy expiry. Returns whether this call recorded an expiry, so the command can refuse
    while the expiry still commits."""
    company_id = db.scalar(scoped(select(Application.company_id), owner_id).where(Application.id == application_id))
    if company_id is None:
        raise not_found()
    company = db.scalar(select(Company).where(Company.id == company_id).with_for_update())
    application = db.scalar(select(Application).where(Application.id == application_id).with_for_update()
                            .execution_options(populate_existing=True))
    return application, company, expire_if_due(db, application, now)


def get_owned_application(db: Session, application_id: str, user_id: str, now: datetime) -> Application:
    """Owner read: 404 for an absent or another client's application; lazy expiry applied."""
    return get_application(db, application_id, now, owner_id=user_id)


def lock_owned_application(db: Session, application_id: str, user_id: str, now: datetime) -> tuple[Application, Company, bool]:
    """Owner command loader (see lock_application)."""
    return lock_application(db, application_id, now, owner_id=user_id)


def owned_applications(db: Session, user_id: str, now: datetime, *, status: str | None = None, company_id: str | None = None) -> list[Application]:
    """The client's applications, newest first, after lazy expiry (so a status filter sees EXPIRED rows as such)."""
    query = owned_query(user_id)
    if company_id is not None:
        query = query.where(Application.company_id == company_id)
    rows = db.scalars(query.order_by(Application.created_at.desc(), Application.id.desc())).all()
    for row in rows:
        expire_if_due(db, row, now)
    return [row for row in rows if status is None or row.status == status]
