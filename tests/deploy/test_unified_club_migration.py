import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def test_unified_club_is_joined_to_the_workstation_migration_chain():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == ["20261109_merge_workstation"]
    assert scripts.get_revision("20261109_merge_workstation").down_revision == (
        "20261021_126", "20261107_111",
    )
    assert scripts.get_revision("20261021_126").down_revision == "20261020_125"


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
