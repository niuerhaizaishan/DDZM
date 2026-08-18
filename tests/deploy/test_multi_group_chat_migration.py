from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)


ROOT = Path(__file__).resolve().parents[2]
PRIMARY_GROUP_CHAT_ID = "00000000-0000-0000-0000-000000000001"
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


def _legacy_database(database_url: str) -> None:
    engine = create_engine(database_url)
    metadata = MetaData()
    inbound = Table(
        "inbound_messages",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("platform_message_id", String(255), nullable=False),
        Column("source_type", String(16), nullable=False),
        Column("chatroom_id", String(255)),
    )
    outbound = Table(
        "outbound_messages",
        metadata,
        Column("id", Uuid, primary_key=True),
    )
    undercover = Table(
        "undercover_sessions",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("active_key", String(32)),
    )
    blame = Table(
        "blame_games",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("active_key", String(32)),
    )
    red_packets = Table(
        "red_packets",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("active_key", String(32)),
    )
    number_bomb = Table(
        "number_bomb_games",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("active_key", String(32)),
    )
    hide_and_seek = Table(
        "hide_and_seek_games",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("user_id", Uuid, nullable=False),
        Column("state", String(16), nullable=False),
    )
    memory = Table(
        "memory_assessment_games",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("active_key", String(32)),
    )
    schedules = Table(
        "random_event_schedules",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("event_date", Date, nullable=False),
        Column("scheduled_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint(
            "event_date",
            "scheduled_at",
            name="random_event_schedules_event_date_scheduled_at_key",
        ),
    )
    events = Table(
        "random_events",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("group_key", String(255), nullable=False),
        Column("state", String(16), nullable=False),
    )
    deliveries = Table(
        "income_report_deliveries",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("report_date", Date, nullable=False),
        Column("report_time", String(5), nullable=False),
        UniqueConstraint(
            "report_date",
            "report_time",
            name="income_report_deliveries_report_date_report_time_key",
        ),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ux_inbound_messages_platform_message_id "
                "ON inbound_messages (platform_message_id)"
            )
        )
        for name, table in (
            ("ux_undercover_one_active_session", "undercover_sessions"),
            ("ux_blame_game_one_active", "blame_games"),
            ("ux_red_packet_one_active", "red_packets"),
            ("ux_number_bomb_one_active", "number_bomb_games"),
            ("ux_memory_assessment_one_active_game", "memory_assessment_games"),
        ):
            connection.execute(
                text(
                    f"CREATE UNIQUE INDEX {name} ON {table} (active_key) "
                    "WHERE active_key IS NOT NULL"
                )
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ux_hide_and_seek_one_selecting_user "
                "ON hide_and_seek_games (user_id) WHERE state = 'selecting'"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ux_random_events_one_active_group "
                "ON random_events (group_key) "
                "WHERE state IN ('signup', 'in_progress', 'tipping')"
            )
        )
        now = datetime(2026, 8, 18, 12, tzinfo=UTC)
        connection.execute(
            inbound.insert(),
            {
                "id": UUID(int=1),
                "platform_message_id": "same-platform-id",
                "source_type": "group",
                "chatroom_id": "legacy-room",
            },
        )
        connection.execute(outbound.insert(), {"id": UUID(int=2)})
        connection.execute(undercover.insert(), {"id": UUID(int=3), "active_key": None})
        connection.execute(blame.insert(), {"id": UUID(int=4), "active_key": None})
        connection.execute(red_packets.insert(), {"id": UUID(int=5), "active_key": None})
        connection.execute(number_bomb.insert(), {"id": UUID(int=6), "active_key": None})
        connection.execute(
            hide_and_seek.insert(),
            {"id": UUID(int=7), "user_id": UUID(int=70), "state": "finished"},
        )
        connection.execute(memory.insert(), {"id": UUID(int=8), "active_key": None})
        connection.execute(
            schedules.insert(),
            {"id": UUID(int=9), "event_date": now.date(), "scheduled_at": now},
        )
        connection.execute(
            events.insert(),
            {"id": UUID(int=10), "group_key": "default", "state": "ended"},
        )
        connection.execute(
            deliveries.insert(),
            {"id": UUID(int=11), "report_date": now.date(), "report_time": "12:00"},
        )


def test_multi_group_migration_backfills_legacy_group_rows(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'multi-group.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    _legacy_database(database_url)
    command.stamp(config, "20260817_44")

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    with engine.connect() as connection:
        primary = connection.execute(
            text("SELECT id, name, chatroom_id FROM group_chats")
        ).one()
        assert UUID(str(primary.id)) == UUID(PRIMARY_GROUP_CHAT_ID)
        assert primary.name == "主群聊待引导"
        assert primary.chatroom_id is None
        for table_name in GROUP_SCOPED_TABLES:
            assert connection.execute(
                text(
                    f"SELECT count(*) FROM {table_name} "
                    "WHERE group_chat_id IS NULL"
                )
            ).scalar_one() == 0
            group_column = next(
                column
                for column in inspector.get_columns(table_name)
                if column["name"] == "group_chat_id"
            )
            assert group_column["nullable"] is (
                table_name in {"inbound_messages", "outbound_messages"}
            )

    assert "group_chat_runtime_states" in inspector.get_table_names()
    for table_name in ("random_event_schedules", "income_report_deliveries"):
        for constraint in inspector.get_unique_constraints(table_name):
            if constraint["name"] is not None:
                assert len(constraint["name"]) <= 63

    command.downgrade(config, "20260817_44")

    inspector = inspect(engine)
    assert "group_chats" not in inspector.get_table_names()
    assert "group_chat_runtime_states" not in inspector.get_table_names()
    for table_name in GROUP_SCOPED_TABLES:
        assert "group_chat_id" not in {
            column["name"] for column in inspector.get_columns(table_name)
        }
