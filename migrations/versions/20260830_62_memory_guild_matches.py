"""Add persistent memory assessment guild matches."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260830_62"
down_revision: str | None = "20260827_61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_guild_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("host_user_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("active_key", sa.String(length=32)),
        sa.Column("planned_series_count", sa.Integer(), nullable=False),
        sa.Column("current_series_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("champion_team_id", sa.Uuid()),
        sa.Column("finish_reason", sa.String(length=64)),
        sa.Column("forced_by_user_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "planned_series_count BETWEEN 1 AND 20",
            name="ck_memory_guild_planned_series_count",
        ),
        sa.ForeignKeyConstraint(["forced_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["host_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_memory_guild_one_active_per_group",
        "memory_guild_matches",
        ["group_chat_id"],
        unique=True,
        sqlite_where=sa.text("active_key IS NOT NULL"),
        postgresql_where=sa.text("active_key IS NOT NULL"),
    )
    op.create_table(
        "memory_guild_teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64)),
        sa.Column("series_wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("slot IN (1, 2)", name="ck_memory_guild_team_slot"),
        sa.ForeignKeyConstraint(["match_id"], ["memory_guild_matches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "name", name="ux_memory_guild_team_match_name"),
        sa.UniqueConstraint("match_id", "slot", name="ux_memory_guild_team_match_slot"),
    )
    op.create_table(
        "memory_guild_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name_snapshot", sa.String(length=64), nullable=False),
        sa.Column("roster_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["memory_guild_matches.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["memory_guild_teams.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_id", "roster_order", name="ux_memory_guild_member_team_order"
        ),
    )
    op.create_index(
        "ux_memory_guild_member_match_user",
        "memory_guild_members",
        ["match_id", "user_id"],
        unique=True,
    )
    op.create_table(
        "memory_guild_series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("win_target", sa.Integer(), nullable=False),
        sa.Column("maximum_decisive_rounds", sa.Integer(), nullable=False),
        sa.Column("is_tiebreaker", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("team1_member_id", sa.Uuid()),
        sa.Column("team2_member_id", sa.Uuid()),
        sa.Column("team1_wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("team2_wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_team_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("sequence >= 1", name="ck_memory_guild_series_sequence"),
        sa.CheckConstraint("win_target >= 1", name="ck_memory_guild_series_win_target"),
        sa.CheckConstraint(
            "maximum_decisive_rounds >= 1",
            name="ck_memory_guild_series_maximum_rounds",
        ),
        sa.ForeignKeyConstraint(["match_id"], ["memory_guild_matches.id"]),
        sa.ForeignKeyConstraint(["team1_member_id"], ["memory_guild_members.id"]),
        sa.ForeignKeyConstraint(["team2_member_id"], ["memory_guild_members.id"]),
        sa.ForeignKeyConstraint(["winner_team_id"], ["memory_guild_teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_id", "sequence", name="ux_memory_guild_series_match_sequence"
        ),
    )
    op.create_table(
        "memory_guild_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("display_seconds", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("answer_deadline", sa.DateTime(timezone=True)),
        sa.Column("outbound_message_id", sa.Uuid()),
        sa.Column("winner_user_id", sa.Uuid()),
        sa.Column("result", sa.String(length=16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("sequence >= 1", name="ck_memory_guild_round_sequence"),
        sa.ForeignKeyConstraint(["match_id"], ["memory_guild_matches.id"]),
        sa.ForeignKeyConstraint(["outbound_message_id"], ["outbound_messages.id"]),
        sa.ForeignKeyConstraint(["series_id"], ["memory_guild_series.id"]),
        sa.ForeignKeyConstraint(["winner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbound_message_id"),
        sa.UniqueConstraint(
            "series_id", "sequence", name="ux_memory_guild_round_series_sequence"
        ),
    )
    op.create_table(
        "memory_guild_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("platform_message_id", sa.String(length=255), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["round_id"], ["memory_guild_rounds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_memory_guild_answer_platform_message",
        "memory_guild_answers",
        ["platform_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ux_memory_guild_answer_platform_message",
        table_name="memory_guild_answers",
    )
    op.drop_table("memory_guild_answers")
    op.drop_table("memory_guild_rounds")
    op.drop_table("memory_guild_series")
    op.drop_index(
        "ux_memory_guild_member_match_user", table_name="memory_guild_members"
    )
    op.drop_table("memory_guild_members")
    op.drop_table("memory_guild_teams")
    op.drop_index(
        "ux_memory_guild_one_active_per_group", table_name="memory_guild_matches"
    )
    op.drop_table("memory_guild_matches")
