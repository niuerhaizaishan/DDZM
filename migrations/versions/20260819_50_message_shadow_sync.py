"""Persist per-group shadow message synchronization state."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_50"
down_revision: str | None = "20260819_49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("group_chat_runtime_states"):
        return
    with op.batch_alter_table("group_chat_runtime_states") as batch_op:
        batch_op.add_column(
            sa.Column(
                "shadow_sync_state",
                sa.String(length=32),
                nullable=False,
                server_default="idle",
            )
        )
        batch_op.add_column(sa.Column("shadow_cursor_at", sa.DateTime()))
        batch_op.add_column(
            sa.Column("shadow_cursor_message_id", sa.String(length=255))
        )
        batch_op.add_column(sa.Column("shadow_last_attempt_at", sa.DateTime()))
        batch_op.add_column(sa.Column("shadow_last_success_at", sa.DateTime()))
        batch_op.add_column(sa.Column("shadow_next_retry_at", sa.DateTime()))
        batch_op.add_column(
            sa.Column(
                "shadow_failure_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("shadow_error_summary", sa.String(length=512))
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("group_chat_runtime_states"):
        return
    existing = {
        column["name"]
        for column in inspector.get_columns("group_chat_runtime_states")
    }
    columns = [
        "shadow_error_summary",
        "shadow_failure_count",
        "shadow_next_retry_at",
        "shadow_last_success_at",
        "shadow_last_attempt_at",
        "shadow_cursor_message_id",
        "shadow_cursor_at",
        "shadow_sync_state",
    ]
    with op.batch_alter_table("group_chat_runtime_states") as batch_op:
        for column in columns:
            if column in existing:
                batch_op.drop_column(column)
