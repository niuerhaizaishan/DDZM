from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, inspect, text

from dzmm_bot.core import schema


ROOT = Path(__file__).resolve().parents[2]


def test_migration_57_adds_performance_defaults(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'performance.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("inbound_messages", metadata, Column("id", Uuid, primary_key=True))
    Table(
        "outbound_messages",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("status", String(32), nullable=False),
    )
    activity_events = Table(
        "ai_activity_events",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("detail", String(32)),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260826_56")

    command.upgrade(config, "20260826_57")

    inspector = inspect(engine)
    assert {
        "performance_settings",
        "performance_reservations",
        "performance_participants",
        "performance_drafts",
        "performance_extension_requests",
        "performance_messages",
        "performance_tips",
    } <= set(inspector.get_table_names())
    assert "performances_enabled" in {
        column["name"] for column in inspector.get_columns("group_chats")
    }
    assert {"deferred_by_performance_id", "performance_defer_key"} <= {
        column["name"] for column in inspector.get_columns("outbound_messages")
    }
    with engine.connect() as connection:
        maximum_duration = connection.execute(
            text(
                "SELECT maximum_duration_minutes FROM performance_settings WHERE id = 1"
            )
        ).scalar_one()
    assert maximum_duration == 360

    with engine.begin() as connection:
        connection.execute(
            activity_events.insert().values(id=uuid4(), detail="长" * 50)
        )

    command.downgrade(config, "20260826_56")
    inspector = inspect(engine)
    assert "performance_settings" not in inspector.get_table_names()
    assert "performances_enabled" not in {
        column["name"] for column in inspector.get_columns("group_chats")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT length(detail) FROM ai_activity_events")
        ).scalar_one() == 32


def test_migration_57_skips_incomplete_legacy_test_schema(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legacy-partial.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("unrelated_legacy_table", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260826_56")

    command.upgrade(config, "20260826_57")

    inspector = inspect(engine)
    assert "performance_settings" not in inspector.get_table_names()

    command.downgrade(config, "20260826_56")


def test_migration_60_persists_inbound_image_metadata(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'performance-images.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    config = Config(str(ROOT / "alembic.ini"))
    schema.Base.metadata.create_all(engine)
    command.stamp(config, "20260827_60")
    command.downgrade(config, "20260826_59")

    metadata = MetaData()
    metadata.reflect(engine)
    groups = metadata.tables["group_chats"]
    users = metadata.tables["users"]
    inbound = metadata.tables["inbound_messages"]
    reservations = metadata.tables["performance_reservations"]
    messages = metadata.tables["performance_messages"]
    group_id = uuid4()
    user_id = uuid4()
    inbound_id = uuid4()
    reservation_id = uuid4()
    message_id = uuid4()
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            groups.insert().values(
                id=group_id.hex,
                name="旧公演群",
                chat_url="https://www.aikda.com/chat?c=old-performance",
                chatroom_id="old-performance",
                listening_enabled=True,
                games_enabled=True,
                enabled_game_types=[],
                random_events_enabled=True,
                announcements_enabled=True,
                adult_shop_enabled=False,
                performances_enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            users.insert().values(
                id=user_id.hex,
                platform_id="legacy-actor",
                display_name="旧演员",
                employee_number=1,
                balance=0,
                profile_text="",
                profile_version=0,
                joined_at=now,
            )
        )
        connection.execute(
            inbound.insert().values(
                id=inbound_id.hex,
                platform_message_id="legacy-performance-message",
                sender_platform_id="legacy-actor",
                content="旧演出内容",
                received_at=now,
                status="accepted",
                ai_memory_eligible=False,
                source_type="group",
                group_chat_id=group_id.hex,
                created_at=now,
            )
        )
        connection.execute(
            reservations.insert().values(
                id=reservation_id.hex,
                owner_user_id=user_id.hex,
                group_chat_id=group_id.hex,
                title="旧公演",
                introduction="旧简介",
                scheduled_at=now,
                event_date=date(2026, 8, 27),
                state="completed",
                started_at=now,
                ended_at=now,
                submitted_at=now,
            )
        )
        connection.execute(
            messages.insert().values(
                id=message_id.hex,
                reservation_id=reservation_id.hex,
                user_id=user_id.hex,
                inbound_message_id=inbound_id.hex,
                created_at=now,
            )
        )

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert {
        "content_type",
        "image_url",
        "image_alt",
        "image_width",
        "image_height",
    } <= {column["name"] for column in inspector.get_columns("inbound_messages")}
    assert "ix_performance_messages_reservation_created" in {
        index["name"] for index in inspector.get_indexes("performance_messages")
    }
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT i.content, i.content_type, p.reservation_id "
                "FROM inbound_messages i "
                "JOIN performance_messages p ON p.inbound_message_id = i.id "
                "WHERE p.id = :id"
            ),
            {"id": message_id.hex},
        ).one()
        assert stored.content == "旧演出内容"
        assert stored.content_type == "text"
        assert str(stored.reservation_id).replace("-", "") == reservation_id.hex

    command.downgrade(config, "20260826_59")
    assert "content_type" not in {
        column["name"] for column in inspect(engine).get_columns("inbound_messages")
    }
    assert "ix_performance_messages_reservation_created" not in {
        index["name"] for index in inspect(engine).get_indexes("performance_messages")
    }
