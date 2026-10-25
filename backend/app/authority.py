"""The mock Госуслуги authority check: POST /api/v1/identity/gosuslugi/verify {inn} (CLIENT, exact Origin,
Idempotency-Key) always confirms a whitelisted ИНН and returns 201 {verification_id, inn, person_name, role,
verified_at, expires_at}. The person is the fixture's synthetic `director_name`; no real ЕСИА/Госуслуги is called, so
several users may confirm (and add) the same ИНН, which a real check would refuse to a non-representative.

Adding a company spends one verification of the same user and ИНН within 30 minutes (`consume`, otherwise 403
AUTHORITY_NOT_VERIFIED); the company keeps it, its questionnaire takes the representative from it, and submission
re-checks it (`require_company_verification`). The seed records a verification of its own for each seeded company.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import idempotency
from .clock import as_utc, iso_utc
from .errors import ApiError
from .fixtures import registry_source
from .idempotency import IdempotencyKey
from .identity import ClientUser, Db, Now
from .models import AuthorityVerification, Company
from .schemas import AuthorityCheckInput

TTL = timedelta(minutes=30)
ROLES = {'LLC': 'Генеральный директор', 'IP': 'Индивидуальный предприниматель'}
router = APIRouter(prefix='/identity/gosuslugi', tags=['identity'])


def not_verified(message: str = 'Подтвердите полномочия через Госуслуги: подтверждение действует 30 минут и подходит '
                                 'для добавления одной компании.') -> ApiError:
    return ApiError(403, 'AUTHORITY_NOT_VERIFIED', message)


def record(db: Session, user_id: str, source: dict, now: datetime, *, method: str) -> AuthorityVerification:
    row = AuthorityVerification(user_id=user_id, inn=source['inn'], person_name=source['director_name'],
                                role=ROLES[source['entity_type']], method=method, verified_at=now, expires_at=now + TTL)
    db.add(row)
    db.flush()
    return row


def public_verification(row: AuthorityVerification) -> dict:
    return {'verification_id': row.id, 'inn': row.inn, 'person_name': row.person_name, 'role': row.role,
            'verified_at': iso_utc(row.verified_at), 'expires_at': iso_utc(row.expires_at)}


@router.post('/verify', status_code=201)
def verify(data: AuthorityCheckInput, request: Request, user: ClientUser, db: Db, now: Now, idempotency_key: IdempotencyKey):
    scope = idempotency.scope_of(request, user.id, idempotency_key, data)
    replayed = idempotency.replay(db, scope)
    if replayed is not None:
        return replayed
    row = record(db, user.id, registry_source(data.inn), now, method='gosuslugi_mock')
    return idempotency.remember(db, scope, public_verification(row), now=now, status=201, resource_id=row.id)


def consume(db: Session, user_id: str, inn: str, verification_id: str | None, now: datetime) -> AuthorityVerification:
    """The onboarding gate: the user's own, unused verification of this ИНН, before its expiry; it is marked used. The
    row lock and the companies' unique link keep it single-use under concurrent requests."""
    row = db.scalar(select(AuthorityVerification).where(AuthorityVerification.id == verification_id).with_for_update()) \
        if verification_id else None
    if row is None or row.user_id != user_id or row.inn != inn or row.used_at is not None or as_utc(row.expires_at) <= now:
        raise not_verified()
    row.used_at = now
    return row


def seeded(db: Session, owner_id: str, source: dict, now: datetime) -> AuthorityVerification:
    """The seed's verification for a seeded company: the fixture's director, already used by that company."""
    row = record(db, owner_id, source, now, method='seed')
    row.used_at = now
    return row


def company_verification(db: Session, company: Company) -> AuthorityVerification | None:
    """The company's verification while it still belongs to the company's owner and ИНН."""
    row = db.get(AuthorityVerification, company.authority_verification_id) if company.authority_verification_id else None
    return row if row is not None and (row.user_id, row.inn) == (company.owner_user_id, company.inn) else None


def require_company_verification(db: Session, company: Company) -> AuthorityVerification:
    """Submission's re-check (403 AUTHORITY_NOT_VERIFIED): a company added before the check existed has none."""
    row = company_verification(db, company)
    if row is None:
        raise not_verified('Полномочия представителя компании не подтверждены через Госуслуги: заявку отправить нельзя.')
    return row
