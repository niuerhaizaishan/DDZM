"""Add persistent Texas Hold'em single-hand cash games."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_46"
down_revision: str | None = "20260818_45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "texas_holdem_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("minimum_players", sa.Integer(), nullable=False),
        sa.Column("maximum_players", sa.Integer(), nullable=False),
        sa.Column("minimum_buy_in", sa.Integer(), nullable=False),
        sa.Column("maximum_buy_in", sa.Integer(), nullable=False),
        sa.Column("daily_start_limit", sa.Integer(), nullable=False),
        sa.Column("signup_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("action_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("small_blind_percent", sa.Integer(), nullable=False),
        sa.Column("big_blind_percent", sa.Integer(), nullable=False),
        sa.CheckConstraint("minimum_players >= 2", name="ck_texas_minimum_players"),
        sa.CheckConstraint("maximum_players <= 9", name="ck_texas_maximum_players"),
        sa.CheckConstraint("minimum_players <= maximum_players", name="ck_texas_player_range"),
        sa.CheckConstraint("minimum_buy_in > 0", name="ck_texas_minimum_buy_in"),
        sa.CheckConstraint("minimum_buy_in <= maximum_buy_in", name="ck_texas_buy_in_range"),
        sa.CheckConstraint("daily_start_limit > 0", name="ck_texas_daily_start_limit"),
        sa.CheckConstraint("signup_timeout_seconds > 0", name="ck_texas_signup_timeout"),
        sa.CheckConstraint("action_timeout_seconds > 0", name="ck_texas_action_timeout"),
        sa.CheckConstraint("small_blind_percent > 0", name="ck_texas_small_blind"),
        sa.CheckConstraint("small_blind_percent < big_blind_percent", name="ck_texas_blind_order"),
        sa.PrimaryKeyConstraint("id"),
    )
    settings = sa.table(
        "texas_holdem_settings",
        *(sa.column(name) for name in (
            "id", "enabled", "minimum_players", "maximum_players",
            "minimum_buy_in", "maximum_buy_in", "daily_start_limit",
            "signup_timeout_seconds", "action_timeout_seconds",
            "small_blind_percent", "big_blind_percent",
        )),
    )
    op.bulk_insert(settings, [{
        "id": 1,
        "enabled": True,
        "minimum_players": 2,
        "maximum_players": 9,
        "minimum_buy_in": 20,
        "maximum_buy_in": 200,
        "daily_start_limit": 1,
        "signup_timeout_seconds": 120,
        "action_timeout_seconds": 120,
        "small_blind_percent": 5,
        "big_blind_percent": 10,
    }])

    op.create_table(
        "texas_holdem_games",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("creator_user_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("street", sa.String(16), nullable=True),
        sa.Column("active_key", sa.String(32), nullable=True),
        sa.Column("buy_in", sa.Integer(), nullable=False),
        sa.Column("deck", sa.JSON(), nullable=True),
        sa.Column("board", sa.JSON(), nullable=False),
        sa.Column("button_seat", sa.Integer(), nullable=True),
        sa.Column("small_blind_seat", sa.Integer(), nullable=True),
        sa.Column("big_blind_seat", sa.Integer(), nullable=True),
        sa.Column("current_seat", sa.Integer(), nullable=True),
        sa.Column("small_blind_amount", sa.Integer(), nullable=True),
        sa.Column("big_blind_amount", sa.Integer(), nullable=True),
        sa.Column("current_bet", sa.Integer(), nullable=False),
        sa.Column("last_full_raise", sa.Integer(), nullable=False),
        sa.Column("signup_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_complete", sa.Boolean(), nullable=False),
        sa.Column("finish_reason", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_texas_holdem_one_active",
        "texas_holdem_games",
        ["group_chat_id"],
        unique=True,
        postgresql_where=sa.text("active_key IS NOT NULL"),
        sqlite_where=sa.text("active_key IS NOT NULL"),
    )

    op.create_table(
        "texas_holdem_players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("seat_number", sa.Integer(), nullable=True),
        sa.Column("hole_cards", sa.JSON(), nullable=True),
        sa.Column("original_buy_in", sa.Integer(), nullable=False),
        sa.Column("stack", sa.Integer(), nullable=False),
        sa.Column("street_contribution", sa.Integer(), nullable=False),
        sa.Column("total_contribution", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("acted", sa.Boolean(), nullable=False),
        sa.Column("raise_open", sa.Boolean(), nullable=False),
        sa.Column("private_outbound_id", sa.Uuid(), nullable=True),
        sa.Column("private_delivery_state", sa.String(16), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["texas_holdem_games.id"]),
        sa.ForeignKeyConstraint(["private_outbound_id"], ["outbound_messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "seat_number"),
        sa.UniqueConstraint("game_id", "user_id"),
    )
    op.create_table(
        "texas_holdem_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=True),
        sa.Column("street", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("requested_amount", sa.Integer(), nullable=True),
        sa.Column("committed_amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["texas_holdem_games.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_message_id"),
    )
    op.create_table(
        "texas_holdem_pots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("pot_number", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("eligible_seats", sa.JSON(), nullable=False),
        sa.Column("winner_seats", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["game_id"], ["texas_holdem_games.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "pot_number"),
    )
    op.create_table(
        "texas_holdem_daily_starts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("play_date", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "play_date"),
    )


def downgrade() -> None:
    op.drop_table("texas_holdem_daily_starts")
    op.drop_table("texas_holdem_pots")
    op.drop_table("texas_holdem_actions")
    op.drop_table("texas_holdem_players")
    op.drop_index("ux_texas_holdem_one_active", table_name="texas_holdem_games")
    op.drop_table("texas_holdem_games")
    op.drop_table("texas_holdem_settings")
