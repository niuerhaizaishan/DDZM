import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from dzmm_bot.core.app import create_app
from tests.core.test_doudizhu_repository import ddz, dealt, NOW


def headers(uid):
    return {'Authorization': f'DoudizhuUid {uid}'}


def test_uid_and_public_private_views(ddz):
    repo = ddz[0]
    room = dealt(ddz)
    client = TestClient(create_app(repo, 'internal', clock=lambda: NOW, doudizhu_game_id='new-card'))
    path = '/api/doudizhu/rooms/' + room['id']
    assert client.get(path).status_code == 401
    assert client.get(path, headers=headers('nobody')).status_code == 200
    hands = []
    for uid in ('host', 'alice', 'bob', 'viewer'):
        res = client.get(path, headers=headers(uid))
        assert res.status_code == 200 and res.headers['cache-control'] == 'no-store'
        data = res.json()
        assert 'hands' not in data and 'code' not in data and data['bottom'] == []
        assert len(data['hand']) == (0 if uid == 'viewer' else 17)
        hands.append(set(data['hand']))
    assert not hands[0] & hands[1] and not hands[1] & hands[2]
    listing = client.get('/api/doudizhu/rooms', headers=headers('viewer')).json()
    assert set(listing[0]) == {
        'id', 'short_id', 'creator_name', 'room_type', 'stake', 'phase', 'occupied'
    }
    assert listing[0]['creator_name'] == 'host'
    assert client.get('/internal/status', headers=headers('host')).status_code in (401, 403)
    preflight = client.options(path, headers={'Origin': 'null', 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
    assert preflight.status_code == 200


def test_chat_limits_idempotency_and_round_scope(ddz):
    repo = ddz[0]
    room = dealt(ddz)
    now = [NOW]
    client = TestClient(create_app(repo, 'internal', clock=lambda: now[0], doudizhu_game_id='new-card'))
    path = '/api/doudizhu/rooms/' + room['id'] + '/chat'
    payload = {'round_id': room['round_id'], 'request_id': str(uuid4()), 'text': '<b>你好</b>'}
    res = client.post(path, headers=headers('viewer'), json=payload)
    assert res.status_code == 200
    assert client.post(path, headers=headers('viewer'), json=payload).json() == res.json()
    assert len(repo.doudizhu_view(UUID(room['id']), 'host', NOW)['messages']) == 1
    for text in ('', 'x' * 301):
        assert client.post(path, headers=headers('viewer'), json={**payload, 'request_id': str(uuid4()), 'text': text}).status_code == 422
    assert client.post(path, headers=headers('viewer'), json={**payload, 'request_id': str(uuid4())}).status_code == 429
    now[0] += timedelta(seconds=2)
    assert client.post(path, headers=headers('viewer'), json={**payload, 'request_id': str(uuid4()), 'text': 'x' * 300}).status_code == 200
    assert client.post(path, headers=headers('host'), json={**payload, 'round_id': str(uuid4())}).status_code == 409
    assert repo.doudizhu_view(UUID(room['id']), 'host', NOW)['version'] == room['version']


def test_sse_reconnect_is_recipient_scoped(ddz):
    from dzmm_bot.core.doudizhu_api import room_events
    repo = ddz[0]
    room = dealt(ddz)
    class Request:
        async def is_disconnected(self):
            return False
    async def first(uid):
        stream = room_events(repo, UUID(room['id']), uid, lambda: NOW, Request())
        value = await anext(stream)
        await stream.aclose()
        return value
    import json
    for uid in ('host', 'viewer'):
        event = asyncio.run(first(uid))
        data = json.loads(event.split('data: ', 1)[1])
        assert len(data['hand']) == (17 if uid == 'host' else 0)


def test_sse_keeps_guest_identity_and_stops_when_disconnected(ddz):
    from dzmm_bot.core.doudizhu_api import room_events
    repo, factory, _ = ddz
    room = dealt(ddz)
    class Request:
        disconnected = False
        async def is_disconnected(self):
            return self.disconnected
    async def check():
        request = Request()
        times = iter((NOW, NOW + timedelta(seconds=1)))
        stream = room_events(repo, UUID(room['id']), 'viewer', lambda: next(times), request)
        assert 'event: snapshot' in await anext(stream)
        assert await anext(stream) == ': heartbeat\n\n'
        request.disconnected = True
        stream = room_events(repo, UUID(room['id']), 'host', lambda: NOW, request)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    asyncio.run(check())


def test_action_validation_and_suggestions(ddz):
    repo = ddz[0]
    room = dealt(ddz)
    client = TestClient(create_app(repo, 'internal', clock=lambda: NOW, doudizhu_game_id='new-card'))
    path = '/api/doudizhu/rooms/' + room['id']
    payload = {'round_id': room['round_id'], 'version': room['version'], 'request_id': str(uuid4()), 'action': 'bid', 'payload': {'score': True}}
    uid = ['host', 'alice', 'bob'][room['turn']]
    assert client.post(path + '/actions', headers=headers(uid), json=payload).status_code == 409
    assert client.get(path + '/suggestions', headers=headers('viewer')).status_code == 409


def test_seat_presence_expires_without_resetting_clock(ddz):
    repo = ddz[0]
    room = dealt(ddz)
    rid = UUID(room['id'])
    one = repo.doudizhu_view(rid, 'alice', NOW)
    assert one['players'][1]['online'] is True
    later = repo.doudizhu_view(rid, 'viewer', NOW + timedelta(seconds=31))
    assert later['players'][1]['online'] is False
    assert later['deadline'] == one['deadline'] and later['version'] == one['version']
