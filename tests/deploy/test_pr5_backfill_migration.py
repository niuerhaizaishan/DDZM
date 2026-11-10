import importlib.util
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def _migration():
    path = ROOT / "migrations/versions/20261012_105_backfill_main_chain.py"
    spec = importlib.util.spec_from_file_location("pr5_backfill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pr6_migrations_merge_into_deployed_main_chain_without_second_head():
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))

    assert script.get_heads() == ["20261109_merge_permanent_honors"]
    assert script.get_revision("20261012_105").down_revision == "20261012_104"
    assert script.get_revision("20261013_106").down_revision == (
        "20261012_105", "20261012_103"
    )
    assert script.get_revision("20261013_107").down_revision == (
        "20261013_106", "20261013_102"
    )
    assert script.get_revision("20261021_126").down_revision == "20261020_125"


def test_pr5_backfill_preserves_live_economy_settings(monkeypatch):
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    lottery = sa.Table(
        "company_lottery_settings", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("red_pool", sa.Integer()),
        sa.Column("red_count", sa.Integer()),
        sa.Column("blue_pool", sa.Integer()),
        sa.Column("ticket_price", sa.Integer()),
        sa.Column("head_prize", sa.Integer()),
        sa.Column("second_prize", sa.Integer()),
        sa.Column("third_prize", sa.Integer()),
        sa.Column("fourth_prize", sa.Integer()),
        sa.Column("fifth_prize", sa.Integer()),
        sa.Column("pool_ceiling", sa.Integer()),
        sa.Column("per_person_cap", sa.Integer()),
        sa.Column("max_tickets_per_day", sa.Integer()),
        sa.Column("max_tickets_per_round", sa.Integer()),
        sa.Column("close_offset_minutes", sa.Integer()),
    )
    rounds = sa.Table(
        "company_lottery_rounds", metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state", sa.String()),
        sa.Column("tickets_sold", sa.Integer()),
        sa.Column("close_at", sa.DateTime()),
        sa.Column("draw_at", sa.DateTime()),
        sa.Column("rules_snapshot", sa.JSON()),
    )
    settings = sa.Table(
        "random_event_settings", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vote_ad_slot_limit", sa.Integer()),
    )
    sa.Table("random_event_ad_slots", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    sa.Table("random_event_ad_slot_drafts", metadata, sa.Column("id", sa.Integer(), primary_key=True))
    items = sa.Table(
        "items", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system_key", sa.String()),
        sa.Column("scratch_reward_min", sa.Integer()),
        sa.Column("scratch_reward_max", sa.Integer()),
    )
    metadata.create_all(engine)
    round_id = uuid4()
    invalid_round_id = uuid4()
    with engine.begin() as connection:
        connection.execute(lottery.insert().values(
            id=1, red_pool=10, red_count=4, blue_pool=6, ticket_price=2,
            head_prize=700, second_prize=130, third_prize=25,
            fourth_prize=7, fifth_prize=2, pool_ceiling=1200,
            per_person_cap=600, max_tickets_per_day=5,
            max_tickets_per_round=2000, close_offset_minutes=20,
        ))
        connection.execute(rounds.insert().values(
            id=round_id, state="open", tickets_sold=0,
            close_at=datetime(2026, 10, 12, 21, 40), draw_at=datetime(2026, 10, 12, 22),
            rules_snapshot={"head_prize": 700},
        ))
        connection.execute(rounds.insert().values(
            id=invalid_round_id, state="open", tickets_sold=0,
            close_at=datetime(2026, 10, 13, 22), draw_at=datetime(2026, 10, 13, 22),
            rules_snapshot={"head_prize": 500},
        ))
        connection.execute(settings.insert().values(id=1, vote_ad_slot_limit=2))
        connection.execute(items.insert(), [
            {"id": 1, "system_key": "scratch_a", "scratch_reward_min": 3, "scratch_reward_max": 8},
            {"id": 2, "system_key": "scratch_b", "scratch_reward_min": 6, "scratch_reward_max": 12},
            {"id": 3, "system_key": "scratch_c", "scratch_reward_min": 11, "scratch_reward_max": 21},
        ])
        module = _migration()
        monkeypatch.setattr(module.op, "get_bind", lambda: connection)
        monkeypatch.setattr(module.op, "execute", lambda statement: connection.execute(
            sa.text(statement) if isinstance(statement, str) else statement
        ))
        module._lottery_economy()
        module._random_event_ad_slots()
        module._scratch_reward_ranges()
        lottery_row = connection.execute(sa.select(lottery)).mappings().one()
        round_rows = {row["id"]: row for row in connection.execute(sa.select(rounds)).mappings()}
        ad_limit = connection.execute(sa.select(settings.c.vote_ad_slot_limit)).scalar_one()
        scratch = connection.execute(sa.select(items.c.scratch_reward_min, items.c.scratch_reward_max).order_by(items.c.id)).all()

    assert (lottery_row["head_prize"], lottery_row["second_prize"], lottery_row["close_offset_minutes"]) == (700, 130, 20)
    assert str(round_rows[round_id]["close_at"]) == "2026-10-12 21:40:00"
    assert round_rows[round_id]["rules_snapshot"] == {"head_prize": 700}
    assert str(round_rows[invalid_round_id]["close_at"]) == "2026-10-13 21:40:00"
    assert round_rows[invalid_round_id]["rules_snapshot"]["head_prize"] == 700
    assert ad_limit == 2
    assert scratch == [(3, 8), (6, 12), (11, 21)]


def test_pr5_backfill_adds_missing_tables_and_columns(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'backfill.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    for name in ("users", "group_chats", "random_event_schedules",
                 "random_event_scenes", "random_event_scene_openings"):
        sa.Table(name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("items", metadata, sa.Column("id", sa.Uuid(), primary_key=True),
             sa.Column("system_key", sa.String()))
    sa.Table(
        "random_event_settings", metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signup_allowed_commands", sa.JSON()),
        sa.Column("in_progress_allowed_commands", sa.JSON()),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20261012_104")

    command.upgrade(config, "20261012_105")

    inspector = sa.inspect(engine)
    assert {"random_event_polls", "random_event_poll_candidates", "random_event_poll_votes",
            "random_event_ad_slots", "random_event_ad_slot_drafts",
            "black_history_entries", "black_history_delete_drafts"} <= set(inspector.get_table_names())
    assert {"vote_enabled", "vote_ad_slot_limit"} <= {
        column["name"] for column in inspector.get_columns("random_event_settings")
    }
    assert {"scratch_reward_min", "scratch_reward_max"} <= {
        column["name"] for column in inspector.get_columns("items")
    }
