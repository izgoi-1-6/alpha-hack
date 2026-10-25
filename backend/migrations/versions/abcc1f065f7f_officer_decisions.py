"""Officer decisions: an assigned officer's preapprove/approve/reject/request_info with phase, amount and reason.

A partial unique index admits at most one preapprove, approve and reject per application (information requests
repeat).

Revision ID: abcc1f065f7f
Revises: f5f74d672e3b
"""
from alembic import op
import sqlalchemy as sa

revision = 'abcc1f065f7f'
down_revision = 'f5f74d672e3b'
branch_labels = None
depends_on = None

ONCE = "action IN ('preapprove', 'approve', 'reject')"


def upgrade():
    op.create_table('officer_decisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('officer_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('phase', sa.String(12), nullable=False),
        sa.Column('action', sa.String(12), nullable=False),
        sa.Column('amount_rub', sa.BigInteger(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('evaluation_id', sa.String(36), sa.ForeignKey('evaluations.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('application_id', 'sequence', name='officer_decision_application_sequence'),
        sa.CheckConstraint("phase IN ('preliminary', 'final')", name='valid_decision_phase'),
        sa.CheckConstraint("action IN ('preapprove', 'approve', 'reject', 'request_info')", name='valid_decision_action'),
        sa.CheckConstraint("(action IN ('preapprove', 'request_info') AND phase = 'preliminary')"
                           " OR (action = 'approve' AND phase = 'final') OR action = 'reject'", name='decision_action_phase'),
        sa.CheckConstraint("(action IN ('preapprove', 'approve') AND amount_rub IS NOT NULL AND amount_rub > 0)"
                           " OR (action IN ('reject', 'request_info') AND amount_rub IS NULL)", name='decision_amount'))
    op.create_index('ix_officer_decisions_application_id', 'officer_decisions', ['application_id'])
    op.create_index('uq_officer_decision_once', 'officer_decisions', ['application_id', 'action'], unique=True,
                    postgresql_where=sa.text(ONCE), sqlite_where=sa.text(ONCE))


def downgrade():
    op.drop_index('uq_officer_decision_once', table_name='officer_decisions')
    op.drop_index('ix_officer_decisions_application_id', table_name='officer_decisions')
    op.drop_table('officer_decisions')
