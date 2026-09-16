import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    Table,
    create_engine,
    text,
)


ROOT = Path(__file__).resolve().parents[2]
VOTE_COMMANDS = ("/事件投票", "/事件投票情况")


def legacy_engine(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'event-vote-gate.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "random_event_settings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("signup_allowed_commands", JSON, nullable=False),
        Column("in_progress_allowed_commands", JSON, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO random_event_settings "
                "(id, signup_allowed_commands, in_progress_allowed_commands) "
                "VALUES (1, :signup, :progress)"
            ),
            {
                "signup": '["/加入", "/退出", "/打卡"]',
                "progress": '["/退出"]',
            },
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260915_76")
    return engine


def _lists(engine) -> tuple[list[str], list[str]]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT signup_allowed_commands, in_progress_allowed_commands "
                "FROM random_event_settings WHERE id = 1"
            )
        ).one()
    # SQLite 把 JSON 存成文本，直接用 text() 读回来是字符串，得自己解析
    return json.loads(row[0]), json.loads(row[1])


def test_gate_migration_appends_the_vote_command(tmp_path, monkeypatch):
    engine = legacy_engine(tmp_path, monkeypatch)
    config = Config(str(ROOT / "alembic.ini"))

    command.upgrade(config, "head")

    signup, progress = _lists(engine)
    for command_name in VOTE_COMMANDS:
        assert command_name in signup
        assert command_name in progress
    # 管理员自己加过的指令不能被抹掉
    assert "/打卡" in signup


def test_gate_migration_is_idempotent(tmp_path, monkeypatch):
    engine = legacy_engine(tmp_path, monkeypatch)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    command.downgrade(config, "20260915_76")
    command.upgrade(config, "head")

    signup, progress = _lists(engine)
    for command_name in VOTE_COMMANDS:
        assert signup.count(command_name) == 1
        assert progress.count(command_name) == 1


def test_gate_migration_downgrades_cleanly(tmp_path, monkeypatch):
    engine = legacy_engine(tmp_path, monkeypatch)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    command.downgrade(config, "20260915_76")

    signup, progress = _lists(engine)
    for command_name in VOTE_COMMANDS:
        assert command_name not in signup
        assert command_name not in progress
    assert signup == ["/加入", "/退出", "/打卡"]
    assert progress == ["/退出"]
