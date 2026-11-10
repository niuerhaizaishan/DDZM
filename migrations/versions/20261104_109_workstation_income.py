"""Atomic daily workstation income receipts; activation is a separate operation."""
from alembic import op
import sqlalchemy as sa

revision = '20261104_109'
down_revision = '20261027_108'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('workstation_income_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('first_settlement_date', sa.Date(), nullable=False),
        sa.Column('last_settled_on', sa.Date()),
        sa.CheckConstraint('id = 1', name='ck_workstation_income_settings_singleton'))
    op.create_table('workstation_income_settlements',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('settlement_date', sa.Date(), primary_key=True),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('components', sa.JSON(), nullable=False),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('amount >= 0', name='ck_workstation_income_amount'))


def downgrade():
    op.drop_table('workstation_income_settlements')
    op.drop_table('workstation_income_settings')
