"""Account-scoped idempotent workstation game actions."""
from alembic import op
import sqlalchemy as sa

revision = "20261027_108"
down_revision = "20261027_107"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("workstation_actions",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("inbound_message_id", sa.Uuid(), sa.ForeignKey("inbound_messages.id"), unique=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("workstation_actions")
