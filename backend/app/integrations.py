"""The simulated Alfa-Business handoff: POST /api/v1/integrations/alfa-business/link (owning CLIENT, APPROVED only)
returns a local demo page address. No bank redirect, signing or disbursement exists; APPROVED does not mean money was
issued. The command changes nothing and follows commands.run_command (ownership 404, replay, expired refusal, state).
"""
from fastapi import APIRouter, Request
from pydantic import Field, StrictStr
from .applications import commands
from .applications.lifecycle import lock_owned_application
from .applications.models import Application
from .errors import ApiError
from .idempotency import IdempotencyKey
from .identity import ClientUser, Db, Now
from .schemas import StrictModel

router = APIRouter(prefix='/integrations/alfa-business', tags=['integrations'])


class LinkInput(StrictModel):
    application_id: StrictStr = Field(max_length=36)


def require_approved(application: Application) -> None:
    if application.status != 'APPROVED':
        raise ApiError(409, 'INVALID_STATUS', 'Переход в Альфа-Бизнес (демо) доступен после окончательного одобрения.')


@router.post('/link')
def alfa_business_link(data: LinkInput, request: Request, user: ClientUser, db: Db, now: Now, idempotency_key: IdempotencyKey):
    return commands.run_command(
        db, request, user.id, idempotency_key, data, now,
        lock=lambda: lock_owned_application(db, data.application_id, user.id, now),
        apply=lambda application, _company: require_approved(application),
        render=lambda application, _company: {'url': f'/demo/alfa-business/{application.id}', 'simulated': True})
