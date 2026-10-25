"""Application documents: one row per stored revision, at most one current revision per requirement.

Check constraints keep review fields present exactly on reviewed revisions and a positive verified value exactly on an
accepted COLLATERAL_VALUATION revision; a partial unique index admits one current (UPLOADED, ACCEPTED or REJECTED)
revision per application and document type.

Revision ID: ee4e652349c6
Revises: abcc1f065f7f
"""
from alembic import op
import sqlalchemy as sa

revision = 'ee4e652349c6'
down_revision = 'abcc1f065f7f'
branch_labels = None
depends_on = None

CURRENT = "status IN ('UPLOADED', 'ACCEPTED', 'REJECTED')"


def upgrade():
    op.create_table('documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('document_type', sa.String(30), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('media_type', sa.String(40), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('storage_key', sa.String(32), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('review_reason', sa.Text(), nullable=True),
        sa.Column('reviewer_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('verified_value_rub', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('application_id', 'document_type', 'revision', name='document_revision'),
        sa.UniqueConstraint('storage_key', name='documents_storage_key_key'),
        sa.CheckConstraint("document_type IN ('BANK_STATEMENT', 'FINANCIAL_REPORT', 'COLLATERAL_OWNERSHIP', 'COLLATERAL_VALUATION')",
                           name='valid_document_type'),
        sa.CheckConstraint("status IN ('UPLOADED', 'ACCEPTED', 'REJECTED', 'SUPERSEDED', 'DELETED')", name='valid_document_status'),
        sa.CheckConstraint("media_type IN ('application/pdf', 'image/jpeg', 'image/png')", name='valid_document_media_type'),
        sa.CheckConstraint('size_bytes BETWEEN 1 AND 20971520', name='valid_document_size'),
        sa.CheckConstraint('revision >= 1 AND length(sha256) = 64', name='valid_document_revision_hash'),
        sa.CheckConstraint("status NOT IN ('ACCEPTED', 'REJECTED') OR "
                           "(reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL AND review_reason IS NOT NULL)",
                           name='document_review_recorded'),
        sa.CheckConstraint("status <> 'UPLOADED' OR (reviewer_id IS NULL AND reviewed_at IS NULL AND review_reason IS NULL)",
                           name='document_unreviewed'),
        sa.CheckConstraint("(document_type = 'COLLATERAL_VALUATION' AND status = 'ACCEPTED' AND verified_value_rub IS NOT NULL "
                           "AND verified_value_rub > 0) OR (NOT (document_type = 'COLLATERAL_VALUATION' AND status = 'ACCEPTED') "
                           "AND verified_value_rub IS NULL)", name='document_verified_value'))
    op.create_index('ix_documents_application_id', 'documents', ['application_id'])
    op.create_index('uq_current_document', 'documents', ['application_id', 'document_type'], unique=True,
                    postgresql_where=sa.text(CURRENT), sqlite_where=sa.text(CURRENT))


def downgrade():
    op.drop_index('uq_current_document', table_name='documents')
    op.drop_index('ix_documents_application_id', table_name='documents')
    op.drop_table('documents')
