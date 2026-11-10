"""track Club player presence

Revision ID: 20261021_128
Revises: 20261021_127
"""

from alembic import op
import sqlalchemy as sa


revision = "20261021_128"
down_revision = "20261021_127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "club_players",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("UPDATE club_players SET last_seen_at = updated_at"))
    op.alter_column("club_players", "last_seen_at", nullable=False)
    op.create_index(
        "ix_club_players_last_seen_at",
        "club_players",
        ["last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_club_players_last_seen_at", table_name="club_players")
    op.drop_column("club_players", "last_seen_at")
