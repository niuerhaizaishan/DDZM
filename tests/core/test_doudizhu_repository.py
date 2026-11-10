from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, InboundRecord, OutboundRecord, PRIMARY_GROUP_CHAT_ID

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


@pytest.fixture
def ddz(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ddz.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = CoreRepository(factory)
    repo.bootstrap_primary_group('https://www.aikda.com/chat?c=test-ddz', NOW)
    for uid in ('host', 'alice', 'bob', 'viewer'):
        repo.create_user(uid, uid, NOW, 0)
    inbound = uuid4()
    with factory.begin() as s:
        s.add(InboundRecord(id=inbound, platform_message_id=str(inbound), sender_platform_id='host',
            content='/斗地主', received_at=NOW, group_chat_id=PRIMARY_GROUP_CHAT_ID, chatroom_id='test-ddz'))
    return repo, factory, inbound


def start(ddz, sent=True):
    repo, factory, inbound = ddz
    room = repo.create_doudizhu_room('host', PRIMARY_GROUP_CHAT_ID, inbound, NOW)
    if sent:
        with factory.begin() as s:
            s.add(OutboundRecord(inbound_message_id=inbound, group_chat_id=PRIMARY_GROUP_CHAT_ID,
                                 text='邀请码', status='sent', content_type='text'))
    return room


def act(repo, room, uid, action, payload=None, now=NOW, request_id=None):
    return repo.doudizhu_action(UUID(room['id']), uid,
        UUID(room['round_id']) if room['round_id'] else None, room['version'],
        request_id or uuid4(), action, payload or {}, now)


def dealt(ddz):
    repo = ddz[0]
    room = start(ddz)
    code = room['code']
    for uid in ('alice', 'bob'):
        room = act(repo, room, uid, 'claim', {'code': code})
    for uid in ('host', 'alice', 'bob'):
        room = act(repo, room, uid, 'ready')
    return room


def test_create_dedup_and_two_claims(ddz):
    repo, factory, inbound = ddz
    room = start(ddz, sent=False)
    assert start(ddz, sent=False)['id'] == room['id']
    assert room['code'].isdigit() and len(room['code']) == 4
    with pytest.raises(ValueError, match='送达'):
        act(repo, room, 'alice', 'claim', {'code': room['code']})
    code = room['code']
    start(ddz)
    room = act(repo, room, 'alice', 'claim', {'code': code})
    room = act(repo, room, 'bob', 'claim', {'code': code})
    assert [p['name'] for p in room['players']] == ['host', 'alice', 'bob']
    assert 'code' not in room
    with pytest.raises(ValueError):
        act(repo, room, 'viewer', 'claim', {'code': code})
    assert repo.doudizhu_view(UUID(room['id']), 'nobody', NOW)['seat'] is None


def test_ready_leave_and_rematch(ddz):
    from dzmm_bot.core.schema import DoudizhuRoundRecord
    repo, factory, _ = ddz
    room = dealt(ddz)
    assert room['phase'] == 'bidding'
    assert len(room['hand']) == 17 and room['bottom'] == []
    old_round = room['round_id']
    room = act(repo, room, 'alice', 'leave')
    assert room['players'][1]['trustee'] is True
    assert len(room['players']) == 3
    with factory.begin() as s:
        row = s.get(DoudizhuRoundRecord, UUID(old_round))
        state = dict(row.state)
        state.update(phase='finished', result={'winner': 'farmers', 'winners': [1, 2], 'spring': None})
        row.state = state
    room = act(repo, room, 'host', 'ready')
    assert room['phase'] == 'finished'
    assert len(room['final_hands']) == 3
    for uid in ('host', 'alice', 'bob'):
        if not next(player for player in room['players'] if player['id'] and player['name'] == uid)['ready']:
            room = act(repo, room, uid, 'ready')
    room = act(repo, room, 'host', 'start')
    assert room['round_id'] != old_round
    assert room['phase'] == 'bidding'


def test_request_id_payload_conflict(ddz):
    repo = ddz[0]
    room = start(ddz)
    request_id = uuid4()
    one = act(repo, room, 'alice', 'claim', {'code': room['code']}, request_id=request_id)
    two = act(repo, room, 'alice', 'claim', {'code': room['code']}, request_id=request_id)
    assert one['version'] == two['version']
    with pytest.raises(ValueError, match='重复请求'):
        act(repo, room, 'alice', 'ready', request_id=request_id)
    with pytest.raises(ValueError, match='更新'):
        act(repo, room, 'bob', 'claim', {'code': room['code']})


def test_redeal_limit_and_restart(ddz):
    repo, factory, _ = ddz
    room = dealt(ddz)
    uid_by_seat = ['host', 'alice', 'bob']
    for _ in range(9):
        room = act(repo, room, uid_by_seat[room['turn']], 'bid', {'score': 0})
    assert room['phase'] == 'cancelled'
    with factory() as s:
        notices = s.scalars(select(OutboundRecord).where(OutboundRecord.inbound_message_id.is_(None))).all()
        assert len(notices) == 1
    assert repo.advance_doudizhu_deadlines(NOW + timedelta(hours=1)) == 0


def test_deadline_persists_across_repository_restart(ddz):
    repo, factory, _ = ddz
    room = dealt(ddz)
    first_turn = room['turn']
    restarted = CoreRepository(factory)
    assert restarted.advance_doudizhu_deadlines(NOW + timedelta(seconds=100)) == 1
    room = restarted.doudizhu_view(UUID(room['id']), 'host', NOW)
    assert room['turn'] == (first_turn + 1) % 3
    assert datetime.fromisoformat(room['deadline']) == NOW + timedelta(seconds=30)


def test_waiting_expiry_and_leave(ddz):
    repo = ddz[0]
    room = start(ddz)
    code = room['code']
    room = act(repo, room, 'alice', 'claim', {'code': code})
    room = act(repo, room, 'alice', 'leave')
    assert room['players'][1] is None
    with pytest.raises(ValueError):
        act(repo, room, 'alice', 'claim', {'code': code}, now=NOW + timedelta(minutes=10))
    repo.advance_doudizhu_deadlines(NOW + timedelta(minutes=10))
    assert repo.doudizhu_view(UUID(room['id']), 'host', NOW)['phase'] == 'cancelled'


def test_rematch_cannot_bypass_settlement_readiness(ddz):
    from dzmm_bot.core.schema import DoudizhuRoundRecord
    repo, factory, _ = ddz
    room = dealt(ddz)
    with factory.begin() as s:
        row = s.get(DoudizhuRoundRecord, UUID(room['round_id']))
        row.state = {**row.state, 'phase': 'finished', 'result': {'winner': 'farmers', 'winners': [1, 2], 'spring': None}}
    with pytest.raises(ValueError, match='所有玩家准备'):
        act(repo, room, 'host', 'rematch')
