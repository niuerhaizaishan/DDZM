"""Both deployed aliases must merge without replaying their data adjustment."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("revision,other", [("107", "123"), ("107", "124"), ("123", "107"), ("123", "108")])
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_equivalent_revision_preserves_existing_values(revision, other, direction):
    path = ROOT / f"migrations/versions/20261020_{revision}_estrus_dark_market_allowance.py"
    spec = importlib.util.spec_from_file_location("archive_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE alembic_version (version_num TEXT)"))
        connection.execute(sa.text("INSERT INTO alembic_version VALUES (:v)"),
                           {"v": f"20261020_{other}"})
        connection.execute(sa.text("CREATE TABLE estrus_settings (g_spot_heat_bonus INTEGER)"))
        connection.execute(sa.text("INSERT INTO estrus_settings VALUES (37)"))
        with patch.object(module.op, "get_bind", return_value=connection):
            getattr(module, direction)()
        assert connection.scalar(sa.text("SELECT g_spot_heat_bonus FROM estrus_settings")) == 37


def test_archive_remains_in_the_single_production_chain():
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == ["20261109_merge_workstation"]
    assert scripts.get_revision("20261021_126").down_revision == "20261020_125"
    assert scripts.get_revision("20261020_mr_archive").down_revision == (
        "20261020_124", "20261020_108"
    )
    assert scripts.get_revision("20261020_123").down_revision == "20261019_122"
    assert scripts.get_revision("20261020_107").down_revision == "20261013_106"


@pytest.mark.parametrize("revision", ["107", "123"])
def test_first_application_still_performs_original_adjustment(revision):
    path = ROOT / f"migrations/versions/20261020_{revision}_estrus_dark_market_allowance.py"
    spec = importlib.util.spec_from_file_location("archive_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE estrus_settings (g_spot_heat_bonus INTEGER)"))
        connection.execute(sa.text("INSERT INTO estrus_settings VALUES (10)"))
        with patch.object(module.op, "get_bind", return_value=connection):
            module.upgrade()
            assert connection.scalar(sa.text("SELECT g_spot_heat_bonus FROM estrus_settings")) == 20
            module.downgrade()
            assert connection.scalar(sa.text("SELECT g_spot_heat_bonus FROM estrus_settings")) == 10


@pytest.mark.parametrize("revision,other", [("108", "124"), ("124", "108")])
@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_charm_alias_does_not_rewrite_already_migrated_titles(revision, other, direction):
    path = ROOT / f"migrations/versions/20261020_{revision}_rename_charm_honors.py"
    spec = importlib.util.spec_from_file_location("charm_alias", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE alembic_version (version_num TEXT)"))
        connection.execute(sa.text("INSERT INTO alembic_version VALUES (:v)"),
                           {"v": f"20261020_{other}"})
        connection.execute(sa.text("CREATE TABLE honor_awards (title_key TEXT, title_name TEXT)"))
        connection.execute(sa.text("INSERT INTO honor_awards VALUES ('charm_m', 'later custom name')"))
        with patch.object(module.op, "get_bind", return_value=connection):
            getattr(module, direction)()
        assert connection.scalar(sa.text("SELECT title_name FROM honor_awards")) == 'later custom name'
