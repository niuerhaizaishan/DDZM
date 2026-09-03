from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, MetaData, String, Table, Text, Uuid, create_engine, select


ROOT = Path(__file__).resolve().parents[2]


def test_performance_and_never_have_i_ever_knowledge_cards_migration(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'knowledge-cards.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    cards = Table(
        "ai_knowledge_cards",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("topic", String(48), nullable=False),
        Column("title", String(128), nullable=False),
        Column("keywords", JSON, nullable=False),
        Column("content", Text, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("priority", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))

    command.stamp(config, "20260831_65")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        inserted = set(connection.scalars(select(cards.c.topic)))
    assert {"performance", "never_have_i_ever"} <= inserted
