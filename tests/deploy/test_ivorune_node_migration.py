from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select


ROOT = Path(__file__).resolve().parents[2]


def test_ivorune_node_migration_rewrites_persisted_platform_urls(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ivorune-node.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    groups = Table(
        "group_chats",
        metadata,
        Column("id", String, primary_key=True),
        Column("chat_url", String),
    )
    settings = Table(
        "game_settings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("company_story_novel_url", String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(groups.insert(), {
            "id": "group-1",
            "chat_url": "https://www.aikda.com/chat?c=group-1",
        })
        connection.execute(settings.insert(), {
            "id": 1,
            "company_story_novel_url": (
                "https://www.dzmm.ai/novel/"
                "66408bb3-60a0-40e1-a434-ee40efee4d27"
            ),
        })
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260908_72")

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.scalar(select(groups.c.chat_url)) == (
            "https://www.ivorune.xyz/chat?c=group-1"
        )
        assert connection.scalar(select(settings.c.company_story_novel_url)) == (
            "https://www.ivorune.xyz/novel/"
            "66408bb3-60a0-40e1-a434-ee40efee4d27"
        )
