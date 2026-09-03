"""Add the global random-event completion reward."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_69"
down_revision: str | None = "20260903_68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("random_event_settings")}
    if "global_completion_reward" not in columns:
        op.add_column(
            "random_event_settings",
            sa.Column(
                "global_completion_reward",
                sa.Integer(),
                nullable=False,
                server_default="6",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("random_event_settings")}
    if "global_completion_reward" in columns:
        op.drop_column("random_event_settings", "global_completion_reward")
