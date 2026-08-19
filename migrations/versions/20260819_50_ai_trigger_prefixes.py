"""Configure AI assistant trigger prefixes."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_50"
down_revision: str | None = "20260819_49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ai_assistant_settings"):
        return
    with op.batch_alter_table("ai_assistant_settings") as batch_op:
        batch_op.add_column(
            sa.Column("trigger_prefixes", sa.JSON(), nullable=True)
        )
    settings = sa.table(
        "ai_assistant_settings", sa.column("trigger_prefixes", sa.JSON())
    )
    op.execute(settings.update().values(trigger_prefixes=["@总监事"]))
    with op.batch_alter_table("ai_assistant_settings") as batch_op:
        batch_op.alter_column(
            "trigger_prefixes", existing_type=sa.JSON(), nullable=False
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("ai_assistant_settings"):
        return
    if "trigger_prefixes" not in {
        column["name"]
        for column in inspector.get_columns("ai_assistant_settings")
    }:
        return
    with op.batch_alter_table("ai_assistant_settings") as batch_op:
        batch_op.drop_column("trigger_prefixes")
