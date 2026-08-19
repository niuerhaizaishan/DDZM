"""Persist the Browser Worker account display name."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_48"
down_revision: str | None = "20260818_47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("worker_instances"):
        return
    with op.batch_alter_table("worker_instances") as batch_op:
        batch_op.add_column(
            sa.Column("account_display_name", sa.String(length=255), nullable=True)
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("worker_instances"):
        return
    if "account_display_name" not in {
        column["name"] for column in inspector.get_columns("worker_instances")
    }:
        return
    with op.batch_alter_table("worker_instances") as batch_op:
        batch_op.drop_column("account_display_name")
