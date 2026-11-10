from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, UserRecord


NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


@pytest.fixture
def mahjong(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'mahjong.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = CoreRepository(factory)
    for uid in ("host", "alice", "bob", "carol", "viewer"):
        repo.create_user(uid, uid, NOW, 1000)
    return repo, factory


def balance(factory, uid):
    with factory() as session:
        return session.scalar(select(UserRecord.balance).where(UserRecord.platform_id == uid))


def create(repo, room_type="coin", request_id=None):
    return repo.create_mahjong_room(
        "host", NOW, room_type=room_type, match_mode="east",
        request_id=request_id or uuid4(),
    )


def act(repo, room, uid, action, payload=None, now=NOW, request_id=None):
    return repo.mahjong_action(
        UUID(room["id"]), uid, room["version"], request_id or uuid4(),
        action, payload or {}, now,
    )


def seated(mahjong, room_type="coin"):
    repo, _ = mahjong
    room = create(repo, room_type)
    for uid in ("alice", "bob", "carol"):
        room = act(repo, room, uid, "claim")
    for uid in ("host", "alice", "bob", "carol"):
        room = act(repo, room, uid, "ready")
    room = act(repo, room, "host", "start")
    return room


def test_coin_room_escrows_exactly_once_and_hides_private_hands(mahjong):
    repo, factory = mahjong
    request_id = uuid4()
    room = create(repo, request_id=request_id)
    duplicate = create(repo, request_id=request_id)
    assert duplicate["id"] == room["id"]
    assert balance(factory, "host") == 990
    claim_id = uuid4()
    room = act(repo, room, "alice", "claim", request_id=claim_id)
    repeated = repo.mahjong_action(
        UUID(room["id"]), "alice", 0, claim_id, "claim", {}, NOW,
    )
    assert repeated["seat"] == 1
    assert balance(factory, "alice") == 990
    viewer = repo.mahjong_view(UUID(room["id"]), "viewer", NOW)
    assert viewer["seat"] is None
    assert "code" not in viewer


def test_waiting_leave_and_expiry_refund_coin_escrow(mahjong):
    repo, factory = mahjong
    room = create(repo)
    room = act(repo, room, "alice", "claim")
    assert balance(factory, "alice") == 990
    room = act(repo, room, "alice", "leave")
    assert balance(factory, "alice") == 1000
    assert room["players"][1] is None
    repo.advance_mahjong_deadlines(NOW + timedelta(minutes=11))
    assert balance(factory, "host") == 1000


def test_four_ready_players_start_authoritative_match(mahjong):
    room = seated(mahjong)
    assert room["phase"] == "playing"
    assert room["game"]["turn"] == 0
    assert len(room["game"]["hand"]) == 14
    viewer = mahjong[0].mahjong_view(UUID(room["id"]), "viewer", NOW)
    assert viewer["game"]["hand"] == []
    assert viewer["game"]["hand_counts"] == [14, 13, 13, 13]


def test_reaction_deadline_is_advanced_by_room_refresh(mahjong, monkeypatch):
    repo, factory = mahjong
    room = seated(mahjong)
    from dzmm_bot.core import mahjong_repository
    from dzmm_bot.core.schema import MahjongRoomRecord

    with factory.begin() as session:
        record = session.get(MahjongRoomRecord, UUID(room["id"]))
        record.state = {
            **record.state,
            "phase": "reaction",
            "deadline": (NOW - timedelta(seconds=1)).isoformat(),
        }
        record.phase = "reaction"
        record.deadline = NOW - timedelta(seconds=1)

    def advance(state, now, wall_factory):
        return {
            **state,
            "phase": "playing",
            "version": state["version"] + 1,
            "deadline": (now + timedelta(seconds=10)).isoformat(),
        }

    monkeypatch.setattr(mahjong_repository, "apply_timeout", advance)
    refreshed = repo.mahjong_view(UUID(room["id"]), "host", NOW)

    assert refreshed["phase"] == "playing"


def test_reaction_action_is_accepted_by_repository(mahjong, monkeypatch):
    repo, _ = mahjong
    monkeypatch.setattr(repo, "_mahjong_wall", lambda: list(range(136)))
    room = seated(mahjong)

    room = act(repo, room, "host", "discard", {"tile": room["game"]["hand"][-1]})
    assert room["phase"] == "reaction"
    room = act(repo, room, "carol", "pass")

    assert room["phase"] == "playing"


def test_match_settlement_pays_winner_the_zero_sum_pot_once(mahjong):
    repo, factory = mahjong
    room = seated(mahjong)
    from dzmm_bot.core.schema import MahjongRoomRecord
    with factory.begin() as session:
        row = session.get(MahjongRoomRecord, UUID(room["id"]))
        state = dict(row.state)
        state.update(
            phase="hand_finished",
            points=[42000, 28000, 19000, 11000],
            round_wind=27,
            hand_number=4,
            deadline=(NOW - timedelta(seconds=1)).isoformat(),
            next={"dealer_continues": False},
            result={"kind": "ron", "dealer_continues": False},
        )
        row.state = state
        row.phase = "hand_finished"
        row.deadline = NOW - timedelta(seconds=1)
    settled = repo.mahjong_view(UUID(room["id"]), "host", NOW)
    assert settled["phase"] == "match_finished"
    assert settled["settlement"]["payouts"] == [40, 0, 0, 0]
    assert settled["settlement"]["outcomes"] == ["win", "loss", "loss", "loss"]
    assert [balance(factory, uid) for uid in ("host", "alice", "bob", "carol")] == [1030, 990, 990, 990]
    repo.mahjong_view(UUID(room["id"]), "host", NOW + timedelta(minutes=1))
    assert [balance(factory, uid) for uid in ("host", "alice", "bob", "carol")] == [1030, 990, 990, 990]

    for uid in ("host", "alice", "bob", "carol"):
        settled = act(repo, settled, uid, "ready")
    settled = act(repo, settled, "host", "start")
    assert settled["phase"] == "playing"
    assert settled["settlement"] is None


def test_casual_room_never_moves_balance(mahjong):
    room = seated(mahjong, "casual")
    assert room["buy_in"] == 0
    assert [balance(mahjong[1], uid) for uid in ("host", "alice", "bob", "carol")] == [1000] * 4
