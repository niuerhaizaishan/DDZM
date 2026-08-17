"""Persist group chat configuration and scope group gameplay."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_45"
down_revision: str | None = "20260817_44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PRIMARY_GROUP_CHAT_ID = UUID("00000000-0000-0000-0000-000000000001")
GROUP_SCOPED_TABLES = (
    "inbound_messages",
    "outbound_messages",
    "undercover_sessions",
    "blame_games",
    "red_packets",
    "number_bomb_games",
    "hide_and_seek_games",
    "memory_assessment_games",
    "random_event_schedules",
    "random_events",
    "income_report_deliveries",
)
NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
}


def _add_group_chat_column(table_name: str) -> None:
    with op.batch_alter_table(
        table_name, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.add_column(sa.Column("group_chat_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            f"fk_{table_name}_group_chat_id_group_chats",
            "group_chats",
            ["group_chat_id"],
            ["id"],
        )
    op.execute(
        sa.text(
            f"UPDATE {table_name} SET group_chat_id = :group_chat_id "
            "WHERE group_chat_id IS NULL"
        ).bindparams(group_chat_id=PRIMARY_GROUP_CHAT_ID)
    )
    with op.batch_alter_table(
        table_name, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.alter_column(
            "group_chat_id",
            existing_type=sa.Uuid(),
            nullable=table_name in {"inbound_messages", "outbound_messages"},
        )


def _drop_group_chat_column(table_name: str) -> None:
    with op.batch_alter_table(
        table_name, naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            f"fk_{table_name}_group_chat_id_group_chats", type_="foreignkey"
        )
        batch_op.drop_column("group_chat_id")


def upgrade() -> None:
    op.create_table(
        "group_chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("chat_url", sa.Text(), nullable=True),
        sa.Column("chatroom_id", sa.String(255), nullable=True),
        sa.Column("listening_enabled", sa.Boolean(), nullable=False),
        sa.Column("games_enabled", sa.Boolean(), nullable=False),
        sa.Column("random_events_enabled", sa.Boolean(), nullable=False),
        sa.Column("announcements_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_group_chats_name"),
        sa.UniqueConstraint("chat_url", name="uq_group_chats_chat_url"),
        sa.UniqueConstraint("chatroom_id", name="uq_group_chats_chatroom_id"),
    )
    now = datetime.now(UTC)
    group_chats = sa.table(
        "group_chats",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("chat_url", sa.Text()),
        sa.column("chatroom_id", sa.String()),
        sa.column("listening_enabled", sa.Boolean()),
        sa.column("games_enabled", sa.Boolean()),
        sa.column("random_events_enabled", sa.Boolean()),
        sa.column("announcements_enabled", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        group_chats,
        [
            {
                "id": PRIMARY_GROUP_CHAT_ID,
                "name": "主群聊待引导",
                "chat_url": None,
                "chatroom_id": None,
                "listening_enabled": False,
                "games_enabled": False,
                "random_events_enabled": False,
                "announcements_enabled": False,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.create_table(
        "group_chat_runtime_states",
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("connection_state", sa.String(16), nullable=False),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_summary", sa.String(512), nullable=True),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.PrimaryKeyConstraint("group_chat_id"),
    )
    runtime_states = sa.table(
        "group_chat_runtime_states",
        sa.column("group_chat_id", sa.Uuid()),
        sa.column("connection_state", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        runtime_states,
        [
            {
                "group_chat_id": PRIMARY_GROUP_CHAT_ID,
                "connection_state": "disabled",
                "updated_at": now,
            }
        ],
    )

    for table_name in GROUP_SCOPED_TABLES:
        _add_group_chat_column(table_name)

    op.drop_index(
        "ux_inbound_messages_platform_message_id", table_name="inbound_messages"
    )
    op.create_index(
        "ux_inbound_messages_group_platform_message_id",
        "inbound_messages",
        ["group_chat_id", "platform_message_id"],
        unique=True,
        postgresql_where=sa.text("source_type = 'group'"),
        sqlite_where=sa.text("source_type = 'group'"),
    )
    op.create_index(
        "ux_inbound_messages_direct_platform_message_id",
        "inbound_messages",
        ["chatroom_id", "platform_message_id"],
        unique=True,
        postgresql_where=sa.text("source_type = 'direct'"),
        sqlite_where=sa.text("source_type = 'direct'"),
    )

    for index_name, table_name in (
        ("ux_undercover_one_active_session", "undercover_sessions"),
        ("ux_blame_game_one_active", "blame_games"),
        ("ux_red_packet_one_active", "red_packets"),
        ("ux_number_bomb_one_active", "number_bomb_games"),
        ("ux_memory_assessment_one_active_game", "memory_assessment_games"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.create_index(
            index_name,
            table_name,
            ["group_chat_id"],
            unique=True,
            postgresql_where=sa.text("active_key IS NOT NULL"),
            sqlite_where=sa.text("active_key IS NOT NULL"),
        )

    op.drop_index(
        "ux_hide_and_seek_one_selecting_user", table_name="hide_and_seek_games"
    )
    op.create_index(
        "ux_hide_and_seek_one_selecting_user",
        "hide_and_seek_games",
        ["group_chat_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'selecting'"),
        sqlite_where=sa.text("state = 'selecting'"),
    )
    op.drop_index("ux_random_events_one_active_group", table_name="random_events")
    op.create_index(
        "ux_random_events_one_active_group",
        "random_events",
        ["group_chat_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('signup', 'in_progress', 'tipping')"),
        sqlite_where=sa.text("state IN ('signup', 'in_progress', 'tipping')"),
    )

    with op.batch_alter_table(
        "random_event_schedules", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_random_event_schedules_event_date_scheduled_at", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_random_event_schedules_group_chat_id_event_date_scheduled_at",
            ["group_chat_id", "event_date", "scheduled_at"],
        )
    with op.batch_alter_table(
        "income_report_deliveries", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_income_report_deliveries_report_date_report_time", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_income_report_deliveries_group_chat_id_report_date_report_time",
            ["group_chat_id", "report_date", "report_time"],
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "income_report_deliveries", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_income_report_deliveries_group_chat_id_report_date_report_time",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_income_report_deliveries_report_date_report_time",
            ["report_date", "report_time"],
        )
    with op.batch_alter_table(
        "random_event_schedules", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_random_event_schedules_group_chat_id_event_date_scheduled_at",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_random_event_schedules_event_date_scheduled_at",
            ["event_date", "scheduled_at"],
        )

    op.drop_index("ux_random_events_one_active_group", table_name="random_events")
    op.create_index(
        "ux_random_events_one_active_group",
        "random_events",
        ["group_key"],
        unique=True,
        postgresql_where=sa.text("state IN ('signup', 'in_progress', 'tipping')"),
        sqlite_where=sa.text("state IN ('signup', 'in_progress', 'tipping')"),
    )
    op.drop_index(
        "ux_hide_and_seek_one_selecting_user", table_name="hide_and_seek_games"
    )
    op.create_index(
        "ux_hide_and_seek_one_selecting_user",
        "hide_and_seek_games",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'selecting'"),
        sqlite_where=sa.text("state = 'selecting'"),
    )
    for index_name, table_name in (
        ("ux_undercover_one_active_session", "undercover_sessions"),
        ("ux_blame_game_one_active", "blame_games"),
        ("ux_red_packet_one_active", "red_packets"),
        ("ux_number_bomb_one_active", "number_bomb_games"),
        ("ux_memory_assessment_one_active_game", "memory_assessment_games"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.create_index(
            index_name,
            table_name,
            ["active_key"],
            unique=True,
            postgresql_where=sa.text("active_key IS NOT NULL"),
            sqlite_where=sa.text("active_key IS NOT NULL"),
        )
    op.drop_index(
        "ux_inbound_messages_direct_platform_message_id",
        table_name="inbound_messages",
    )
    op.drop_index(
        "ux_inbound_messages_group_platform_message_id",
        table_name="inbound_messages",
    )
    op.create_index(
        "ux_inbound_messages_platform_message_id",
        "inbound_messages",
        ["platform_message_id"],
        unique=True,
    )

    for table_name in reversed(GROUP_SCOPED_TABLES):
        _drop_group_chat_column(table_name)
    op.drop_table("group_chat_runtime_states")
    op.drop_table("group_chats")
