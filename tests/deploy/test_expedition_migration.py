import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_expedition_migration_preserves_players_and_round_trips(tmp_path):
    path=Path(__file__).resolve().parents[2]/'migrations/versions/20261022_mr_expedition.py'
    spec=importlib.util.spec_from_file_location('expedition_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=sa.create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE mistrealm_players (id VARCHAR(32) PRIMARY KEY)'))
        connection.execute(sa.text("INSERT INTO mistrealm_players VALUES ('existing-player')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert 'mistrealm_expeditions' in sa.inspect(connection).get_table_names()
            assert connection.execute(sa.text('SELECT COUNT(*) FROM mistrealm_players')).scalar()==1
            module.downgrade()
            assert 'mistrealm_expeditions' not in sa.inspect(connection).get_table_names()
            assert connection.execute(sa.text('SELECT COUNT(*) FROM mistrealm_players')).scalar()==1
