"""Nine independent workstation slots; missing rows represent the free Lv1 set."""
from alembic import op
import sqlalchemy as sa

revision = "20261021_106"
down_revision = "20261016_105"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workstation_components",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("category_number", sa.Integer(), primary_key=True),
        sa.Column("highest_level", sa.Integer(), nullable=False),
        sa.Column("active_level", sa.Integer(), nullable=False),
        sa.Column("equipped", sa.Boolean(), nullable=False),
        sa.CheckConstraint("category_number BETWEEN 1 AND 9", name="ck_workstation_category"),
        sa.CheckConstraint("highest_level BETWEEN 1 AND 10", name="ck_workstation_level"),
        sa.CheckConstraint("active_level BETWEEN 1 AND highest_level", name="ck_workstation_active"),
    )
    op.create_table(
        "workstation_upgrades",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("inbound_message_id", sa.Uuid(), sa.ForeignKey("inbound_messages.id"), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), sa.ForeignKey("group_chats.id"), nullable=False),
        sa.Column("category_number", sa.Integer(), nullable=False),
        sa.Column("from_level", sa.Integer(), nullable=False),
        sa.Column("to_level", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("credit_used", sa.Integer(), nullable=False),
        sa.Column("cash_paid", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("category_number BETWEEN 1 AND 9", name="ck_workstation_upgrade_category"),
        sa.CheckConstraint("from_level BETWEEN 1 AND 9 AND to_level = from_level + 1", name="ck_workstation_upgrade_step"),
        sa.CheckConstraint("price >= 0 AND credit_used >= 0 AND cash_paid >= 0 AND price = credit_used + cash_paid", name="ck_workstation_upgrade_payment"),
    )
    op.create_index("ix_workstation_upgrades_user_id", "workstation_upgrades", ["user_id"])


def downgrade():
    op.drop_table("workstation_upgrades")
    op.drop_table("workstation_components")
