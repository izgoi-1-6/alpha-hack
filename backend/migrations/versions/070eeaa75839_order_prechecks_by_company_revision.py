"""order prechecks by company revision

Revision ID: 070eeaa75839
Revises: 477de883cdb2
Create Date: 2026-10-24 22:34:40.106315

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '070eeaa75839'
down_revision: Union[str, None] = '477de883cdb2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('prechecks', sa.Column('company_version', sa.Integer(), nullable=True))
    op.execute(sa.text('''WITH ranked AS (
        SELECT id, row_number() OVER (PARTITION BY company_id ORDER BY checked_at, id) AS revision
        FROM prechecks
    ) UPDATE prechecks SET company_version = ranked.revision FROM ranked WHERE prechecks.id = ranked.id'''))
    op.alter_column('prechecks', 'company_version', nullable=False)
    op.create_unique_constraint('precheck_company_revision', 'prechecks', ['company_id', 'company_version'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('precheck_company_revision', 'prechecks', type_='unique')
    op.drop_column('prechecks', 'company_version')
