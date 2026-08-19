"""Configure enabled games per group chat."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260819_49"
down_revision: str | None = "20260819_48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_GAME_TYPES = [
    "red_packet",
    "hide_and_seek",
    "memory_assessment",
    "undercover",
    "blame_bomb",
    "number_bomb",
    "texas_holdem",
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("group_chats"):
        return
    with op.batch_alter_table("group_chats") as batch_op:
        batch_op.add_column(
            sa.Column("enabled_game_types", sa.JSON(), nullable=True)
        )
    groups = sa.table(
        "group_chats", sa.column("enabled_game_types", sa.JSON())
    )
    op.execute(groups.update().values(enabled_game_types=_ALL_GAME_TYPES))
    with op.batch_alter_table("group_chats") as batch_op:
        batch_op.alter_column(
            "enabled_game_types", existing_type=sa.JSON(), nullable=False
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("group_chats"):
        return
    if "enabled_game_types" not in {
        column["name"] for column in inspector.get_columns("group_chats")
    }:
        return
    with op.batch_alter_table("group_chats") as batch_op:
        batch_op.drop_column("enabled_game_types")
