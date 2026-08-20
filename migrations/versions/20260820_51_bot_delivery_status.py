"""Track Bot long-message delivery status."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260820_51"
down_revision: str | None = "20260819_50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("worker_instances"):
        return
    columns = {column["name"] for column in inspector.get_columns("worker_instances")}
    with op.batch_alter_table("worker_instances") as batch_op:
        if "bot_delivery_state" not in columns:
            batch_op.add_column(
                sa.Column(
                    "bot_delivery_state",
                    sa.String(length=32),
                    nullable=False,
                    server_default="unknown",
                )
            )
        if "bot_delivery_error" not in columns:
            batch_op.add_column(
                sa.Column("bot_delivery_error", sa.String(length=255), nullable=True)
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("worker_instances"):
        return
    columns = {column["name"] for column in inspector.get_columns("worker_instances")}
    with op.batch_alter_table("worker_instances") as batch_op:
        if "bot_delivery_error" in columns:
            batch_op.drop_column("bot_delivery_error")
        if "bot_delivery_state" in columns:
            batch_op.drop_column("bot_delivery_state")
