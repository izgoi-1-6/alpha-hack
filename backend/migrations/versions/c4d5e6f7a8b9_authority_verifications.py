"""Mock Госуслуги authority verifications and the company's link to the one it was added with.

`authority_verifications` records each confirmation (user, ИНН, the fixture's person and role, method `gosuslugi_mock`
or `seed`, verified/expiry/used times). `companies.authority_verification_id` is nullable and unique: companies added
before this revision keep null (synthetic test data; they cannot submit an application), every new company stores the
verification it spent, and no verification adds two companies.

Revision ID: c4d5e6f7a8b9
Revises: b3c1d2e4f5a6
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c1d2e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('authority_verifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('inn', sa.String(12), nullable=False),
        sa.Column('person_name', sa.String(100), nullable=False),
        sa.Column('role', sa.String(100), nullable=False),
        sa.Column('method', sa.String(20), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("method IN ('gosuslugi_mock','seed')", name='valid_verification_method'))
    op.create_index('ix_authority_verifications_user_id', 'authority_verifications', ['user_id'])
    op.add_column('companies', sa.Column('authority_verification_id', sa.String(36), nullable=True))
    op.create_foreign_key('fk_companies_authority_verification_id', 'companies', 'authority_verifications',
                          ['authority_verification_id'], ['id'])
    op.create_unique_constraint('company_authority_verification', 'companies', ['authority_verification_id'])


def downgrade():
    op.drop_constraint('company_authority_verification', 'companies', type_='unique')
    op.drop_constraint('fk_companies_authority_verification_id', 'companies', type_='foreignkey')
    op.drop_column('companies', 'authority_verification_id')
    op.drop_index('ix_authority_verifications_user_id', table_name='authority_verifications')
    op.drop_table('authority_verifications')
