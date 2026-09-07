"""Add check-in rewards to rank configuration."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_70"
down_revision: str | None = "20260903_69"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("ranks")}
    if "checkin_reward" not in columns:
        op.add_column(
            "ranks",
            sa.Column(
                "checkin_reward", sa.Integer(), nullable=False, server_default="0"
            ),
        )
        op.execute(
            "UPDATE ranks SET checkin_reward = COALESCE("
            "(SELECT checkin_reward FROM game_settings WHERE id = 1), 5)"
        )
        if op.get_bind().dialect.name != "sqlite":
            op.alter_column("ranks", "checkin_reward", server_default=None)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("ranks")}
    if "checkin_reward" in columns:
        op.drop_column("ranks", "checkin_reward")
