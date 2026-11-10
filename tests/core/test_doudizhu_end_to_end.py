from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from dzmm_bot.core.app import create_app
from dzmm_bot.core.schema import BalanceTransactionRecord, OutboundRecord, UserRecord
from tests.core.test_doudizhu_api import headers
from tests.core.test_doudizhu_repository import ddz, NOW


def test_group_to_complete_game_and_rematch_without_currency(ddz):
    repo, factory, _ = ddz
    client = TestClient(create_app(repo, 'internal', clock=lambda: NOW, doudizhu_game_id='new-card'))
    created = client.post('/api/doudizhu/rooms', headers=headers('host'), json={})
    assert created.status_code == 200
    room = created.json()
    with factory.begin() as s:
        rid = room['id']
        balances = [(u.id, u.balance) for u in s.scalars(select(UserRecord)).all()]
        ledger_ids = list(s.scalars(select(BalanceTransactionRecord.id)))
    path = '/api/doudizhu/rooms/' + rid
    users = ['host', 'alice', 'bob']

    def view(uid):
        response = client.get(path, headers=headers(uid))
        assert response.status_code == 200
        return response.json()

    def action(uid, name, payload=None):
        current = view(uid)
        response = client.post(path + '/actions', headers=headers(uid), json={
            'round_id': current['round_id'], 'version': current['version'],
            'request_id': str(uuid4()), 'action': name, 'payload': payload or {}})
        assert response.status_code == 200, response.text
        return response.json()

    for uid in users[1:]:
        action(uid, 'claim')
    for uid in users:
        state = action(uid, 'ready')
    first_round = state['round_id']
    assert state['phase'] == 'bidding'
    assert sum(len(view(uid)['hand']) for uid in users) == 51
    assert view('viewer')['bottom'] == []
    action(users[state['turn']], 'bid', {'score': 3})
    for _ in range(200):
        state = view('viewer')
        assert state['hand'] == [] and 'hands' not in state and 'code' not in state
        held = [c for uid in users for c in view(uid)['hand']]
        played = [c for event in state['events'] if event.get('play') for c in event['play']['cards']]
        assert sorted(held + played) == list(range(54))
        if state['phase'] == 'finished':
            break
        uid = users[state['turn']]
        suggestions = client.get(path + '/suggestions', headers=headers(uid))
        assert suggestions.status_code == 200
        choices = suggestions.json()
        if choices:
            action(uid, 'play', {'cards': choices[0]['cards']})
        else:
            action(uid, 'pass')
    assert state['phase'] == 'finished'
    repo.advance_doudizhu_deadlines(NOW)
    with factory() as s:
        notices = s.scalars(select(OutboundRecord).where(OutboundRecord.inbound_message_id.is_(None))).all()
        assert notices == []
        assert [(u.id, u.balance) for u in s.scalars(select(UserRecord)).all()] == balances
        assert list(s.scalars(select(BalanceTransactionRecord.id))) == ledger_ids
    for uid in users:
        state = action(uid, 'ready')
    state = action('host', 'start')
    assert state['phase'] == 'bidding' and state['round_id'] != first_round
    assert view('viewer')['hand'] == []
