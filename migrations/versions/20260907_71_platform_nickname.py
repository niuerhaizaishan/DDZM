"""Store cached DZMM platform nicknames for employees."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_71"
down_revision: str | None = "20260907_70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "platform_nickname" not in columns:
        op.add_column("users", sa.Column("platform_nickname", sa.String(64)))
    if "platform_nickname_synced_at" not in columns:
        op.add_column(
            "users", sa.Column("platform_nickname_synced_at", sa.DateTime(timezone=True))
        )
    if "platform_nickname_attempted_at" not in columns:
        op.add_column(
            "users", sa.Column("platform_nickname_attempted_at", sa.DateTime(timezone=True))
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users")}
    for column in (
        "platform_nickname_attempted_at",
        "platform_nickname_synced_at",
        "platform_nickname",
    ):
        if column in columns:
            op.drop_column("users", column)
