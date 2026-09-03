"""Add the persistent Never Have I Ever game."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_64"
down_revision: str | None = "20260831_63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("group_chats"):
        groups = sa.table(
            "group_chats",
            sa.column("id", sa.Uuid()),
            sa.column("enabled_game_types", sa.JSON()),
        )
        for group_id, enabled_game_types in bind.execute(
            sa.select(groups.c.id, groups.c.enabled_game_types)
        ):
            game_types = list(enabled_game_types or [])
            if "never_have_i_ever" not in game_types:
                bind.execute(
                    groups.update()
                    .where(groups.c.id == group_id)
                    .values(enabled_game_types=[*game_types, "never_have_i_ever"])
                )
    op.create_table(
        "never_have_i_ever_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("signup_timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("statement_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("response_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "never_have_i_ever_games",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("host_user_id", sa.Uuid(), nullable=False),
        sa.Column("active_key", sa.String(length=32)),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("initial_player_count", sa.Integer(), nullable=False),
        sa.Column("current_speaker_order", sa.Integer()),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("signup_deadline", sa.DateTime(timezone=True)),
        sa.Column("statement_deadline", sa.DateTime(timezone=True)),
        sa.Column("response_deadline", sa.DateTime(timezone=True)),
        sa.Column("free_punishment_started_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("finish_reason", sa.String(length=64)),
        sa.CheckConstraint(
            "state IN ('signup', 'awaiting_statement', 'awaiting_responses', "
            "'free_punishment', 'completed', 'cancelled', 'expired', "
            "'forced_ended')",
            name="ck_never_have_i_ever_game_state",
        ),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["host_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_never_have_i_ever_one_active",
        "never_have_i_ever_games",
        ["group_chat_id"],
        unique=True,
        sqlite_where=sa.text("active_key IS NOT NULL"),
        postgresql_where=sa.text("active_key IS NOT NULL"),
    )
    op.create_table(
        "never_have_i_ever_players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("roster_order", sa.Integer(), nullable=False),
        sa.Column("hearts", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eliminated_at", sa.DateTime(timezone=True)),
        sa.Column("elimination_reason", sa.String(length=64)),
        sa.CheckConstraint(
            "hearts BETWEEN 0 AND 5", name="ck_never_have_i_ever_hearts"
        ),
        sa.CheckConstraint(
            "state IN ('signup', 'active', 'eliminated', 'withdrawn')",
            name="ck_never_have_i_ever_player_state",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["never_have_i_ever_games.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "roster_order"),
        sa.UniqueConstraint("game_id", "user_id"),
    )
    op.create_table(
        "never_have_i_ever_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("speaker_user_id", sa.Uuid(), nullable=False),
        sa.Column("statement", sa.Text()),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("statement_at", sa.DateTime(timezone=True)),
        sa.Column("response_deadline", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("statement_timed_out", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "state IN ('awaiting_statement', 'awaiting_responses', 'settled', "
            "'statement_timeout')",
            name="ck_never_have_i_ever_round_state",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["never_have_i_ever_games.id"]),
        sa.ForeignKeyConstraint(["speaker_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "sequence"),
    )
    op.create_table(
        "never_have_i_ever_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("choice", sa.String(length=32), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "choice IN ('deduct', 'keep', 'timeout_deduct')",
            name="ck_never_have_i_ever_response_choice",
        ),
        sa.ForeignKeyConstraint(["round_id"], ["never_have_i_ever_rounds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("never_have_i_ever_responses")
    op.drop_table("never_have_i_ever_rounds")
    op.drop_table("never_have_i_ever_players")
    op.drop_index(
        "ux_never_have_i_ever_one_active",
        table_name="never_have_i_ever_games",
    )
    op.drop_table("never_have_i_ever_games")
    op.drop_table("never_have_i_ever_settings")
