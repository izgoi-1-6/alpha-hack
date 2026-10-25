"""InfoRequest rows: system-detected gaps here, officer requests from Task 5, under the same rules.

trusted_source: a named source (registry, turnover or bki), no officer, no requested fields; it is closed by a
retry-check that obtains complete source evidence, never by client answers. client_answers: no source and at least
one requested answer path; an officer request also carries officer_id.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Application, InfoRequest

SOURCES = ('registry', 'turnover', 'bki')


def create_info_request(db: Session, application: Application, *, kind: str, source: str | None, requested_fields: list[str],
                        question: str, now: datetime, officer_id: str | None = None) -> InfoRequest:
    if kind == 'trusted_source':
        valid = source in SOURCES and officer_id is None and not requested_fields
    else:
        valid = kind == 'client_answers' and source is None and bool(requested_fields)
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
