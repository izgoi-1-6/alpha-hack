"""Application lifecycle entities: Application, Evaluation, InfoRequest, StatusHistory, OfficerDecision and simulated
Notification.

UUID strings, integer RUB in BigInteger columns and timezone-aware timestamps, as in app.models. `sequence` columns
order an application's evaluations, history rows and officer decisions deterministically even when a test clock does
not advance; they are internal and not part of the public API.
"""
from datetime import datetime
from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
from ..models import new_id

STATUSES = ('DRAFT', 'CHECKING', 'WAIT_EXTERNAL', 'MANUAL_REVIEW', 'NEED_INFO', 'PREAPPROVED', 'DOCS_UPLOADED',
            'DOCS_REWORK', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED')
# Submitted and not finished: at most one per company and product (drafts and terminal rows are unconstrained).
ACTIVE_STATUSES = ('CHECKING', 'WAIT_EXTERNAL', 'MANUAL_REVIEW', 'NEED_INFO', 'PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK')
TERMINAL_STATUSES = ('APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED')
RULES = tuple(f'R{number}' for number in range(1, 13))


def sql_in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


ACTIVE_PREDICATE = sql_in('status', ACTIVE_STATUSES)


class Application(Base):
    __tablename__ = 'applications'
    __table_args__ = (
        CheckConstraint(sql_in('status', STATUSES), name='valid_application_status'),
        CheckConstraint('current_stage BETWEEN 1 AND 6', name='valid_application_stage'),
        Index('uq_active_application_company_product', 'company_id', 'product_id', unique=True,
              postgresql_where=text(ACTIVE_PREDICATE), sqlite_where=text(ACTIVE_PREDICATE)),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'), index=True)
    product_id: Mapped[str] = mapped_column(String(80))
    recommendation_snapshot_id: Mapped[str] = mapped_column(ForeignKey('recommendation_snapshots.id'))
    status: Mapped[str] = mapped_column(String(20))
    answers: Mapped[dict] = mapped_column(JSON)
    current_stage: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    requested_amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    indicative_limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    scored_limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    preapproved_amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    final_amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    preapproved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preapproval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_version: Mapped[str] = mapped_column(String(80))
    rules_version: Mapped[str] = mapped_column(String(80))
    submitted_input_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Evaluation(Base):
    """One immutable check result (submission or retry); prior evaluations and their source payloads are kept."""
    __tablename__ = 'evaluations'
    __table_args__ = (
        UniqueConstraint('application_id', 'sequence', name='evaluation_application_sequence'),
        CheckConstraint(sql_in('rule', RULES), name='valid_evaluation_rule'),
        CheckConstraint(sql_in('outcome', STATUSES), name='valid_evaluation_outcome'),
        CheckConstraint("risk IS NULL OR risk IN ('low', 'medium', 'high')", name='valid_evaluation_risk'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    score: Mapped[int | None] = mapped_column(Integer)
    risk: Mapped[str | None] = mapped_column(String(10))
    factors: Mapped[dict | None] = mapped_column(JSON)
    rule: Mapped[str] = mapped_column(String(3))
    scored_limit_rub: Mapped[int | None] = mapped_column(BigInteger)
    outcome: Mapped[str] = mapped_column(String(20))
    reasons: Mapped[list] = mapped_column(JSON)
    sources: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InfoRequest(Base):
    """A gap to close: system-detected (officer_id null) or officer-authored."""
    __tablename__ = 'info_requests'
    __table_args__ = (
        CheckConstraint("kind IN ('client_answers', 'trusted_source')", name='valid_info_request_kind'),
        CheckConstraint("source IS NULL OR source IN ('registry', 'turnover', 'bki')", name='valid_info_request_source'),
        CheckConstraint("(kind = 'trusted_source' AND source IS NOT NULL AND officer_id IS NULL)"
                        " OR (kind = 'client_answers' AND source IS NULL)", name='info_request_kind_rules'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    officer_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    kind: Mapped[str] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(10))
    requested_fields: Mapped[list] = mapped_column(JSON)
    question: Mapped[str] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StatusHistory(Base):
    __tablename__ = 'status_history'
    __table_args__ = (
        UniqueConstraint('application_id', 'sequence', name='status_history_application_sequence'),
        CheckConstraint(sql_in('to_status', STATUSES), name='valid_history_status'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    reason_code: Mapped[str] = mapped_column(String(40))
    reason_text: Mapped[str] = mapped_column(Text)
    application_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


DECISION_ACTIONS = ('preapprove', 'approve', 'reject', 'request_info')
ONCE_PREDICATE = "action IN ('preapprove', 'approve', 'reject')"


class OfficerDecision(Base):
    """An assigned officer's decision with its reason. Preapprove and request_info are preliminary, approve is final,
    reject is either. A preapprove, approve or reject happens at most once per application (a partial unique index
    backs the row lock and version check, so no replay or race can record a second one); information requests repeat."""
    __tablename__ = 'officer_decisions'
    __table_args__ = (
        UniqueConstraint('application_id', 'sequence', name='officer_decision_application_sequence'),
        CheckConstraint("phase IN ('preliminary', 'final')", name='valid_decision_phase'),
        CheckConstraint(sql_in('action', DECISION_ACTIONS), name='valid_decision_action'),
        CheckConstraint("(action IN ('preapprove', 'request_info') AND phase = 'preliminary')"
                        " OR (action = 'approve' AND phase = 'final') OR action = 'reject'", name='decision_action_phase'),
        CheckConstraint("(action IN ('preapprove', 'approve') AND amount_rub IS NOT NULL AND amount_rub > 0)"
                        " OR (action IN ('reject', 'request_info') AND amount_rub IS NULL)", name='decision_amount'),
        Index('uq_officer_decision_once', 'application_id', 'action', unique=True,
              postgresql_where=text(ONCE_PREDICATE), sqlite_where=text(ONCE_PREDICATE)),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    officer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    phase: Mapped[str] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(12))
    amount_rub: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    evaluation_id: Mapped[str | None] = mapped_column(ForeignKey('evaluations.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    """A simulated in-app message; nothing is dispatched. `status_history_id` ties it to the transition it reports."""
    __tablename__ = 'notifications'
    __table_args__ = (CheckConstraint("channel = 'demo_in_app'", name='demo_notification_channel'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    status_history_id: Mapped[str | None] = mapped_column(ForeignKey('status_history.id'), index=True)
    event_code: Mapped[str] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
