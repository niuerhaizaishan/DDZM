import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def test_unified_club_is_joined_to_the_workstation_migration_chain():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == ["20261109_merge_permanent_honors"]
    assert scripts.get_revision("20261109_merge_permanent_honors").down_revision == (
        "20261109_merge_workstation", "20261109_111_permanent_honors",
    )
    assert scripts.get_revision("20261109_merge_workstation").down_revision == (
        "20261103_130", "20261107_111",
    )
    assert scripts.get_revision("20261021_126").down_revision == "20261020_125"
    assert scripts.get_revision("20261021_127").down_revision == "20261021_126"
    assert scripts.get_revision("20261021_128").down_revision == "20261021_127"
    assert scripts.get_revision("20261021_129").down_revision == "20261021_128"
    assert scripts.get_revision("20261022_mr_expedition").down_revision == "20261021_129"
    assert scripts.get_revision("20261103_130").down_revision == "20261022_mr_expedition"


def test_club_card_tables_generate_postgresql_upgrade_sql():
    environment = {
        **os.environ,
        "DZMM_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/database",
    }
    result = subprocess.run(
        [str(ROOT / ".venv/bin/alembic"), "upgrade", "20261021_128:20261021_129", "--sql"],
        cwd=ROOT, env=environment, text=True, capture_output=True, check=True,
    )
    assert "CREATE TABLE club_card_rooms" in result.stdout
    assert "CREATE TABLE club_card_requests" in result.stdout
    assert "CREATE TABLE club_card_messages" in result.stdout
    assert "CREATE TABLE club_card_hands" in result.stdout


def test_club_presence_generates_postgresql_upgrade_sql():
    environment = {
        **os.environ,
        "DZMM_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/database",
    }
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/alembic"),
            "upgrade",
            "20261021_127:20261021_128",
            "--sql",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "ADD COLUMN last_seen_at TIMESTAMP WITH TIME ZONE" in result.stdout
    assert "ix_club_players_last_seen_at" in result.stdout


def test_club_daily_tasks_generate_postgresql_upgrade_sql():
    environment = {
        **os.environ,
        "DZMM_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/database",
    }
    result = subprocess.run(
        [
            str(ROOT / ".venv/bin/alembic"),
            "upgrade",
            "20261021_126:20261021_127",
            "--sql",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "ADD COLUMN claim_date DATE" in result.stdout
    assert "ux_club_task_claim_daily" in result.stdout


def test_unified_club_generates_postgresql_upgrade_sql():
    environment = {
        **os.environ,
        "DZMM_DATABASE_URL": "postgresql+psycopg://user:pass@localhost/database",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "20261020_125:20261021_126",
            "--sql",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "CREATE TABLE club_players" in result.stdout
    assert "REFERENCES club_players" in result.stdout
    assert "CREATE TABLE club_task_claims" in result.stdout
    assert "ALTER TABLE doudizhu_rooms ALTER COLUMN group_chat_id DROP NOT NULL" in result.stdout
