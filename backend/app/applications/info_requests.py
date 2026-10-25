"""InfoRequest rows: system-detected gaps and officer requests, under the same rules.

trusted_source: a named source (registry, turnover or bki), no officer, no requested fields; it is closed by a
retry-check that obtains complete source evidence, never by client answers. client_answers: no source and at least
one requested questionnaire answer path; an officer request also carries officer_id. It is closed by the owner's
respond-info, which may set only those paths.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Application, InfoRequest
from .schemas import CollateralAnswer
from .stages import ANSWER_FIELDS

SOURCES = ('registry', 'turnover', 'bki')
# Paths a client_answers request may name: every saved questionnaire answer, and each pledge detail. Company snapshot,
# consents and BKI categories are not answers, so they can never be requested from the client.
ANSWER_PATHS = ANSWER_FIELDS + tuple(f'collateral.{key}' for key in CollateralAnswer.model_fields)


def create_info_request(db: Session, application: Application, *, kind: str, source: str | None, requested_fields: list[str],
                        question: str, now: datetime, officer_id: str | None = None) -> InfoRequest:
    if kind == 'trusted_source':
        valid = source in SOURCES and officer_id is None and not requested_fields
    else:
        valid = (kind == 'client_answers' and source is None and bool(requested_fields)
                 and all(path in ANSWER_PATHS for path in requested_fields))
    if not valid:
        raise ValueError(f'invalid {kind} info request')
    row = InfoRequest(application_id=application.id, officer_id=officer_id, kind=kind, source=source,
                      requested_fields=list(requested_fields), question=question, created_at=now)
    db.add(row)
    db.flush()
    return row


def open_info_request(db: Session, application_id: str) -> InfoRequest | None:
    """The unresolved request, if any (at most one is open at a time)."""
    return db.scalar(select(InfoRequest).where(InfoRequest.application_id == application_id, InfoRequest.resolved_at.is_(None))
                     .order_by(InfoRequest.created_at.desc(), InfoRequest.id.desc()).limit(1))


def answered_paths(patch: dict) -> list[str]:
    """The answer paths a partial answers object sets: top-level names, `collateral.<key>` for each pledge detail."""
    paths = []
    for name, value in patch.items():
        if name == 'collateral' and isinstance(value, dict):
            paths.extend(f'collateral.{key}' for key in value)
        else:
            paths.append(name)
    return paths


def unrequested(requested: list[str], answered: list[str]) -> list[str]:
    """Answered paths no requested path covers (a requested `collateral` covers every pledge detail)."""
    return [path for path in answered if path not in requested and path.split('.')[0] not in requested]


def unanswered(requested: list[str], answered: list[str]) -> list[str]:
    """Requested paths the answers do not set (a pledge detail answers a requested `collateral`)."""
    return [path for path in requested if not any(given == path or given.startswith(path + '.') for given in answered)]
