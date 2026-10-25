"""Application lifecycle: applications, evaluations, info requests, status history, simulated notifications.

Adds the consents.application_id foreign key and a partial unique index admitting one active submitted application
per company and product (drafts and terminal applications are unconstrained).

Revision ID: f5f74d672e3b
Revises: 6ca90a120ab3
"""
from alembic import op
import sqlalchemy as sa

revision = 'f5f74d672e3b'
down_revision = '6ca90a120ab3'
branch_labels = None
depends_on = None

STATUSES = ('DRAFT', 'CHECKING', 'WAIT_EXTERNAL', 'MANUAL_REVIEW', 'NEED_INFO', 'PREAPPROVED', 'DOCS_UPLOADED',
            'DOCS_REWORK', 'APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED')
ACTIVE = ('CHECKING', 'WAIT_EXTERNAL', 'MANUAL_REVIEW', 'NEED_INFO', 'PREAPPROVED', 'DOCS_UPLOADED', 'DOCS_REWORK')
RULES = tuple(f'R{number}' for number in range(1, 13))


def sql_in(column, values):
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def money(name):
    return sa.Column(name, sa.BigInteger(), nullable=True)


def moment(name, nullable=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table('applications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('company_id', sa.String(36), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('product_id', sa.String(80), nullable=False),
        sa.Column('recommendation_snapshot_id', sa.String(36), sa.ForeignKey('recommendation_snapshots.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('answers', sa.JSON(), nullable=False),
        sa.Column('current_stage', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        moment('submitted_at'),
        sa.Column('assignee_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        money('requested_amount_rub'), money('indicative_limit_rub'), money('scored_limit_rub'),
        money('preapproved_amount_rub'), money('final_amount_rub'),
        moment('preapproved_at'), moment('preapproval_expires_at'),
        sa.Column('catalog_version', sa.String(80), nullable=False),
        sa.Column('rules_version', sa.String(80), nullable=False),
        sa.Column('submitted_input_snapshot', sa.JSON(), nullable=True),
        moment('created_at', nullable=False), moment('updated_at', nullable=False),
        sa.CheckConstraint(sql_in('status', STATUSES), name='valid_application_status'),
        sa.CheckConstraint('current_stage BETWEEN 1 AND 6', name='valid_application_stage'))
    op.create_index('ix_applications_company_id', 'applications', ['company_id'])
    op.create_index('uq_active_application_company_product', 'applications', ['company_id', 'product_id'], unique=True,
                    postgresql_where=sa.text(sql_in('status', ACTIVE)), sqlite_where=sa.text(sql_in('status', ACTIVE)))
    op.create_table('evaluations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('risk', sa.String(10), nullable=True),
        sa.Column('factors', sa.JSON(), nullable=True),
        sa.Column('rule', sa.String(3), nullable=False),
        money('scored_limit_rub'),
        sa.Column('outcome', sa.String(20), nullable=False),
        sa.Column('reasons', sa.JSON(), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=False),
        moment('created_at', nullable=False),
        sa.UniqueConstraint('application_id', 'sequence', name='evaluation_application_sequence'),
        sa.CheckConstraint(sql_in('rule', RULES), name='valid_evaluation_rule'),
        sa.CheckConstraint(sql_in('outcome', STATUSES), name='valid_evaluation_outcome'),
        sa.CheckConstraint("risk IS NULL OR risk IN ('low', 'medium', 'high')", name='valid_evaluation_risk'))
    op.create_index('ix_evaluations_application_id', 'evaluations', ['application_id'])
    op.create_table('info_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('officer_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('source', sa.String(10), nullable=True),
        sa.Column('requested_fields', sa.JSON(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('response', sa.Text(), nullable=True),
        moment('responded_at'), moment('resolved_at'), moment('created_at', nullable=False),
        sa.CheckConstraint("kind IN ('client_answers', 'trusted_source')", name='valid_info_request_kind'),
        sa.CheckConstraint("source IS NULL OR source IN ('registry', 'turnover', 'bki')", name='valid_info_request_source'),
        sa.CheckConstraint("(kind = 'trusted_source' AND source IS NOT NULL AND officer_id IS NULL)"
                           " OR (kind = 'client_answers' AND source IS NULL)", name='info_request_kind_rules'))
    op.create_index('ix_info_requests_application_id', 'info_requests', ['application_id'])
    op.create_table('status_history',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(20), nullable=True),
        sa.Column('to_status', sa.String(20), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reason_code', sa.String(40), nullable=False),
        sa.Column('reason_text', sa.Text(), nullable=False),
        sa.Column('application_version', sa.Integer(), nullable=False),
        moment('created_at', nullable=False),
        sa.UniqueConstraint('application_id', 'sequence', name='status_history_application_sequence'),
        sa.CheckConstraint(sql_in('to_status', STATUSES), name='valid_history_status'))
    op.create_index('ix_status_history_application_id', 'status_history', ['application_id'])
    op.create_table('notifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('application_id', sa.String(36), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('status_history_id', sa.String(36), sa.ForeignKey('status_history.id'), nullable=True),
        sa.Column('event_code', sa.String(60), nullable=False),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        moment('created_at', nullable=False),
        sa.CheckConstraint("channel = 'demo_in_app'", name='demo_notification_channel'))
    op.create_index('ix_notifications_application_id', 'notifications', ['application_id'])
    op.create_index('ix_notifications_status_history_id', 'notifications', ['status_history_id'])
    op.create_index('ix_consents_application_id', 'consents', ['application_id'])
    op.create_foreign_key('fk_consents_application_id', 'consents', 'applications', ['application_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_consents_application_id', 'consents', type_='foreignkey')
    op.drop_index('ix_consents_application_id', table_name='consents')
    op.drop_index('ix_notifications_status_history_id', table_name='notifications')
    op.drop_index('ix_notifications_application_id', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_status_history_application_id', table_name='status_history')
    op.drop_table('status_history')
    op.drop_index('ix_info_requests_application_id', table_name='info_requests')
    op.drop_table('info_requests')
    op.drop_index('ix_evaluations_application_id', table_name='evaluations')
    op.drop_table('evaluations')
    op.drop_index('uq_active_application_company_product', table_name='applications')
    op.drop_index('ix_applications_company_id', table_name='applications')
    op.drop_table('applications')
