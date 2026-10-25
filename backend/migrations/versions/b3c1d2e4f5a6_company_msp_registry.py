"""Company SME-register flag: `companies.msp_registry`, nullable (unknown while the registry source is unavailable).

The registry facts that feed eligibility and later prefill (`msp_registry`, `tax_regime`, `employees`) also enter each
new precheck's `registry_payload` JSON, which needs no schema change.

Revision ID: b3c1d2e4f5a6
Revises: ee4e652349c6
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c1d2e4f5a6'
down_revision = 'ee4e652349c6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('companies', sa.Column('msp_registry', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('companies', 'msp_registry')
