"""Store the configured company story novel link."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260908_72"
down_revision: str | None = "20260907_71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("game_settings")}
    if "company_story_novel_url" not in columns:
        op.add_column("game_settings", sa.Column("company_story_novel_url", sa.Text()))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("game_settings")}
    if "company_story_novel_url" in columns:
        op.drop_column("game_settings", "company_story_novel_url")
