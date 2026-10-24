"""Persist immutable preliminary recommendation snapshots.

Revision ID: 6ca90a120ab3
Revises: 070eeaa75839
"""
from alembic import op
import sqlalchemy as sa

revision = '6ca90a120ab3'
down_revision = '070eeaa75839'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('recommendation_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('precheck_id', sa.String(36), sa.ForeignKey('prechecks.id'), nullable=False),
        sa.Column('need', sa.JSON(), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('catalog_version', sa.String(80), nullable=False),
        sa.Column('rules_version', sa.String(80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_recommendation_snapshots_company_id', 'recommendation_snapshots', ['company_id'])

def downgrade():
    op.drop_index('ix_recommendation_snapshots_company_id', table_name='recommendation_snapshots')
    op.drop_table('recommendation_snapshots')
