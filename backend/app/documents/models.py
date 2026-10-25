"""Document: one stored revision of a required application document.

Each requirement (application, document_type) has at most one current revision (UPLOADED, ACCEPTED or REJECTED; a
partial unique index backs the row locks). A replacement supersedes the current revision, whose content stays readable;
a deletion marks it DELETED and its bytes are removed. Review fields are present exactly for reviewed revisions, and a
positive verified value exists exactly on an ACCEPTED COLLATERAL_VALUATION revision (accepted revisions never change).
`storage_key` is a random private file name, never derived from the upload name and never returned by the API.
"""
from datetime import datetime
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from ..applications.models import sql_in
from ..db import Base
from ..models import new_id

DOCUMENT_TYPES = ('BANK_STATEMENT', 'FINANCIAL_REPORT', 'COLLATERAL_OWNERSHIP', 'COLLATERAL_VALUATION')
DOCUMENT_STATUSES = ('UPLOADED', 'ACCEPTED', 'REJECTED', 'SUPERSEDED', 'DELETED')
CURRENT_STATUSES = ('UPLOADED', 'ACCEPTED', 'REJECTED')
MEDIA_TYPES = ('application/pdf', 'image/jpeg', 'image/png')
MAX_FILE_BYTES = 20 * 1024 * 1024
CURRENT_PREDICATE = sql_in('status', CURRENT_STATUSES)
REVIEW_RECORDED = ("status NOT IN ('ACCEPTED', 'REJECTED') OR "
                   "(reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL)")
UNREVIEWED = "status <> 'UPLOADED' OR (reviewer_id IS NULL AND reviewed_at IS NULL AND review_reason IS NULL)"
VERIFIED_VALUE = ("(document_type = 'COLLATERAL_VALUATION' AND status = 'ACCEPTED' AND verified_value_rub IS NOT NULL "
                  "AND verified_value_rub > 0) OR (NOT (document_type = 'COLLATERAL_VALUATION' AND status = 'ACCEPTED') "
                  "AND verified_value_rub IS NULL)")


class Document(Base):
    __tablename__ = 'documents'
    __table_args__ = (
        UniqueConstraint('application_id', 'document_type', 'revision', name='document_revision'),
        CheckConstraint(sql_in('document_type', DOCUMENT_TYPES), name='valid_document_type'),
        CheckConstraint(sql_in('status', DOCUMENT_STATUSES), name='valid_document_status'),
        CheckConstraint(sql_in('media_type', MEDIA_TYPES), name='valid_document_media_type'),
        CheckConstraint(f'size_bytes BETWEEN 1 AND {MAX_FILE_BYTES}', name='valid_document_size'),
        CheckConstraint('revision >= 1 AND length(sha256) = 64', name='valid_document_revision_hash'),
        CheckConstraint(REVIEW_RECORDED, name='document_review_recorded'),
        CheckConstraint(UNREVIEWED, name='document_unreviewed'),
        CheckConstraint(VERIFIED_VALUE, name='document_verified_value'),
        Index('uq_current_document', 'application_id', 'document_type', unique=True,
              postgresql_where=text(CURRENT_PREDICATE), sqlite_where=text(CURRENT_PREDICATE)),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey('applications.id'), index=True)
    document_type: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer)
    original_name: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    status: Mapped[str] = mapped_column(String(12))
    review_reason: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    verified_value_rub: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
