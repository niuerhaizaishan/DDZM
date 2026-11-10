from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_gamefy_workstation as builder
from configure_workstation_income import configure
from backfill_workstation_accessories import run as backfill
from workstation_deploy_config import database_url
from dzmm_bot.core.schema import (Base, UserRecord, WorkstationComponentRecord,
    WorkstationAccessoryRecord, WorkstationIncomeSettingsRecord, WorkstationIncomeRecord)


def test_release_uses_isolated_output_without_rewriting_source(tmp_path):
    sources = [ROOT / 'gamefy-workstation' / p for p in ['dzmm.json', 'publish/config.js', 'publish/index.html']]
    before = {p: p.read_bytes() for p in sources}
    project = builder.build(tmp_path / 'project', release=True, api_base_url='https://workstation.example.test', card_id=123456)
    files = builder.check(project, release=True)
    assert len(files) == 7 and not (project / 'publish/assets').exists()
    assert json.loads((project / 'dzmm.json').read_text())['cardId'] == 123456
    assert 'https://workstation.example.test' in (project / 'publish/config.js').read_text()
    assert all(p.read_bytes() == content for p, content in before.items())
    (project / 'publish/extra-private.txt').write_text('not allowed')
    with pytest.raises(ValueError, match='Unexpected file'):
        builder.check(project, release=True)


@pytest.mark.parametrize('url,card', [('', 123), ('http://example.test', 123),
    ('https://user:secret@example.test', 123), ('https://example.test?key=x', 123),
    ('https://example.test#fragment', 123), ('https://example.test:invalid', 123),
    ('https://example.test', None), ('https://example.test', True), ('https://example.test', -1)])
def test_invalid_release_settings_create_no_output(tmp_path, url, card):
    destination = tmp_path / 'project'
    with pytest.raises(ValueError):
        builder.build(destination, release=True, api_base_url=url, card_id=card)
    assert not destination.exists()


def test_settings_precedence_and_offline_default(tmp_path, monkeypatch):
    private = tmp_path / 'config.local.json'
    private.write_text(json.dumps({'workstation': {'apiBaseUrl': 'https://local.example.test', 'cardId': 123}}))
    monkeypatch.delenv('DZMM_WORKSTATION_API_BASE_URL', raising=False)
    monkeypatch.delenv('DZMM_GAMEFY_CARD_ID', raising=False)
    assert builder.build_settings(release=True, config_path=private) == ('https://local.example.test', 123)
    monkeypatch.setenv('DZMM_WORKSTATION_API_BASE_URL', 'https://env.example.test')
    monkeypatch.setenv('DZMM_GAMEFY_CARD_ID', '456')
    assert builder.build_settings(release=True, config_path=private) == ('https://env.example.test', 456)
    assert builder.build_settings(release=True, api_base_url='https://arg.example.test', card_id=789, config_path=private) == ('https://arg.example.test', 789)
    assert builder.build_settings(release=False, config_path=private) == ('', None)
    with pytest.raises(ValueError, match='Release requires'):
        builder.build_settings(release=True, api_base_url='', card_id=789)


@pytest.fixture
def operations_database(tmp_path, monkeypatch):
    url = 'sqlite+pysqlite:///' + str(tmp_path / 'operations.db')
    monkeypatch.setenv('DZMM_DATABASE_URL', url)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        user = UserRecord(platform_id='example-employee', display_name='示例员工', employee_number=1,
                          balance=128, joined_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        session.add(user)
        session.flush()
        user_id = user.id
    yield engine, user_id
    engine.dispose()


def test_income_configuration_dry_run_and_reenable_preserve_settlement(operations_database):
    engine, user_id = operations_database
    first = date(2026, 1, 1)
    assert configure()['before'] is None
    assert configure(enabled=True, first_date=first)['apply'] is False
    assert configure()['before'] is None
    with pytest.raises(ValueError, match='first-date'):
        configure(enabled=True, apply=True)
    configure(enabled=True, first_date=first, apply=True)
    with Session(engine) as session, session.begin():
        session.get(WorkstationIncomeSettingsRecord, 1).last_settled_on = first
        session.add(WorkstationIncomeRecord(user_id=user_id, settlement_date=first, amount=0,
                    components=[], settled_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert configure(enabled=False, apply=True)['after']['last_settled_on'] == first.isoformat()
    configure(enabled=True, apply=True)
    configure(enabled=True, first_date=first, apply=True)
    with pytest.raises(ValueError, match='cannot be changed'):
        configure(enabled=True, first_date=date(2026, 1, 2), apply=True)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkstationIncomeRecord)) == 1
        assert session.get(UserRecord, user_id).balance == 128
        assert session.get(WorkstationIncomeSettingsRecord, 1).last_settled_on == first


def test_backfill_is_idempotent_preserves_unequipped_items_and_balance(operations_database):
    engine, user_id = operations_database
    with Session(engine) as session, session.begin():
        for number in range(1, 10):
            session.add(WorkstationComponentRecord(user_id=user_id, category_number=number,
                        highest_level=3, active_level=3, equipped=True))
        session.add(WorkstationAccessoryRecord(user_id=user_id, accessory_number=101, equipped=False))
    assert backfill(False) == {'apply': False, 'users': 1, 'planned': 5, 'inserted': 0}
    assert backfill(True)['inserted'] == 5
    assert backfill(True)['inserted'] == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(WorkstationAccessoryRecord)) == 6
        assert session.get(WorkstationAccessoryRecord, (user_id, 101)).equipped is False
        assert session.get(UserRecord, user_id).balance == 128


def test_private_env_file_and_process_precedence(tmp_path, monkeypatch):
    private = tmp_path / 'server.env'
    private.write_text('export DZMM_DATABASE_URL="sqlite:///private.db" # comment\n')
    monkeypatch.delenv('DZMM_DATABASE_URL', raising=False)
    assert database_url(private) == 'sqlite:///private.db'
    monkeypatch.setenv('DZMM_DATABASE_URL', 'sqlite:///environment.db')
    assert database_url(private) == 'sqlite:///environment.db'


def test_isolated_demo_builds_its_own_generated_files(tmp_path):
    from preview_workstation_game import demo_app
    with demo_app(tmp_path / 'demo.sqlite3', 8895) as (app, repository), TestClient(app) as client:
        page = client.get('/')
        assert page.status_code == 200 and '本地联动试玩' in page.text
        for filename in ['art.js', 'style.css', 'workstation.js', 'game.js', 'config.js']:
            assert client.get('/' + filename).status_code == 200
        token = json.loads(re.search(r'token:("[^"]+")', page.text)[1])
        response = client.get('/api/gamefy/workstation', headers={'Authorization': 'Bearer ' + token})
        assert response.status_code == 200 and response.json()['display_name'] == '示例员工'


def test_asset_inventory_matches_the_shipped_files():
    from audit_workstation_assets import audit
    directory = ROOT / 'src/dzmm_bot/admin/static/workstation'
    report = audit(directory)
    assert not report['missing'] and not report['unreferenced']
    expected = json.loads((ROOT / 'docs/workstation-assets.json').read_text())
    assert report == expected
