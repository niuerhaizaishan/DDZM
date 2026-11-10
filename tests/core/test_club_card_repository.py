from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from dzmm_bot.core.schema import ClubCardRoomRecord, UserRecord
from tests.core.test_mahjong_repository import NOW, mahjong


def balance(factory, uid):
    with factory() as session:
        return session.scalar(select(UserRecord.balance).where(UserRecord.platform_id == uid))


def act(repo, room, uid, action, payload=None, request_id=None):
    return repo.club_card_action(
        room["game"], UUID(room["id"]), uid, room["version"],
        request_id or uuid4(), action, payload or {}, NOW,
    )


def test_texas_coin_hand_is_zero_sum_and_requests_are_idempotent(mahjong):
    repo, factory = mahjong
    room = repo.create_club_card_room(
        "texas", "host", NOW, room_type="coin", stake=10, request_id=uuid4(),
    )
    room = act(repo, room, "alice", "claim")
    room = act(repo, room, "host", "ready")
    room = act(repo, room, "alice", "ready")
    start_id = uuid4()
    room = act(repo, room, "host", "start", request_id=start_id)
    repeated = repo.club_card_action(
        "texas", UUID(room["id"]), "host", room["version"] - 1,
        start_id, "start", {}, NOW,
    )
    assert repeated["hand_number"] == 1
    assert balance(factory, "host") == 990
    assert balance(factory, "alice") == 990

    room = act(repo, room, "host", "fold")

    assert room["phase"] == "hand_finished"
    assert balance(factory, "host") + balance(factory, "alice") == 2000
    assert balance(factory, "host") == 999
    assert balance(factory, "alice") == 1001


def test_blackjack_pvp_requires_two_players_and_settles_without_a_dealer(mahjong):
    repo, factory = mahjong
    room = repo.create_club_card_room(
        "blackjack", "host", NOW, room_type="coin", stake=10, request_id=uuid4(),
    )
    with pytest.raises(ValueError, match="至少需要 2 人"):
        room = act(repo, room, "host", "ready")
        act(repo, room, "host", "start")
    room = repo.club_card_view("blackjack", UUID(room["id"]), "host", NOW)
    room = act(repo, room, "alice", "claim")
    room = act(repo, room, "alice", "ready")
    if room["me"]["uid"] != "host":
        room = repo.club_card_view("blackjack", UUID(room["id"]), "host", NOW)
    room = act(repo, room, "host", "ready")
    room = act(repo, room, "host", "start")

    assert "dealer" not in room["state"]
    assert balance(factory, "host") == 990
    assert balance(factory, "alice") == 990


def test_finished_hand_stays_on_settlement_until_everyone_readies(mahjong):
    repo, _ = mahjong
    room = repo.create_club_card_room(
        "zhajinhua", "host", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )
    room = act(repo, room, "alice", "claim")
    room = act(repo, room, "host", "ready")
    room = act(repo, room, "alice", "ready")
    room = act(repo, room, "host", "start")
    room = act(repo, room, "alice", "fold")
    assert room["phase"] == "hand_finished"

    assert all(cards and all(card is not None for card in cards)
               for cards in room["state"]["hands"].values())
    assert set(room["state"]["hand_ranks"]) == set(room["state"]["hands"])

    room = act(repo, room, "host", "ready")
    assert room["phase"] == "hand_finished"
    with pytest.raises(ValueError, match="所有玩家准备"):
        act(repo, room, "host", "start")
    room = act(repo, room, "alice", "ready")
    room = act(repo, room, "host", "start")

    assert room["phase"] == "playing"
    assert room["hand_number"] == 2
    assert room["players"][0]["name"] == "host"
    assert room["players"][1]["name"] == "alice"
    assert room["ready"] == []


@pytest.mark.parametrize("game", ["texas", "zhajinhua", "blackjack"])
def test_spectator_can_join_after_a_hand_for_the_next_hand(mahjong, game):
    repo, factory = mahjong
    room = repo.create_club_card_room(
        game, "host", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )
    room = act(repo, room, "alice", "claim")
    with factory.begin() as session:
        record = session.get(ClubCardRoomRecord, UUID(room["id"]))
        record.phase = "hand_finished"
        record.state = {
            "phase": "hand_finished", "players": list(record.seats),
            "hands": {}, "winners": [], "payouts": {},
        }
        record.version += 1

    spectator = repo.club_card_view(game, UUID(room["id"]), "bob", NOW)
    joined = act(repo, spectator, "bob", "claim")

    assert joined["phase"] == "hand_finished"
    assert [player["uid"] for player in joined["players"]] == ["host", "alice", "bob"]
    assert joined["ready"] == []
    assert joined["state"]["players"] == spectator["state"]["players"]


def test_card_turn_times_out_and_auto_folds_when_a_call_is_required(mahjong):
    repo, _ = mahjong
    room = repo.create_club_card_room(
        "texas", "host", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )
    room = act(repo, room, "alice", "claim")
    room = act(repo, room, "host", "ready")
    room = act(repo, room, "alice", "ready")
    room = act(repo, room, "host", "start")

    assert room["state"]["turn_deadline"] == (NOW + timedelta(seconds=30)).isoformat()

    assert repo.advance_club_card_deadlines(NOW + timedelta(seconds=31)) == 1
    timed_out = repo.club_card_view("texas", UUID(room["id"]), "host", NOW + timedelta(seconds=31))

    assert timed_out["phase"] == "hand_finished"
    assert timed_out["state"]["last_action"] == "玩家超时，自动弃牌"
    assert "turn_deadline" not in timed_out["state"]


def test_card_player_cannot_occupy_two_active_rooms(mahjong):
    repo, _ = mahjong
    first = repo.create_club_card_room(
        "texas", "host", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )
    second = repo.create_club_card_room(
        "blackjack", "alice", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )

    with pytest.raises(ValueError, match="已经在.+牌桌"):
        act(repo, second, "host", "claim")
    spectator_view = repo.club_card_view("blackjack", UUID(second["id"]), "host", NOW)
    assert all(player["uid"] != "host" for player in spectator_view["players"])
    with pytest.raises(ValueError, match="已经在.+牌桌"):
        repo.create_club_card_room(
            "zhajinhua", "host", NOW, room_type="casual", stake=0,
            request_id=uuid4(),
        )

    first = act(repo, first, "host", "leave")
    assert first["phase"] == "closed"
    joined = act(repo, second, "host", "claim")
    assert any(player["uid"] == "host" for player in joined["players"])


def test_card_player_cannot_create_or_join_another_club_module(mahjong):
    repo, _ = mahjong
    repo.create_club_card_room(
        "texas", "host", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )

    with pytest.raises(ValueError, match="已经在德州扑克房间"):
        repo.create_mahjong_room(
            "host", NOW, room_type="casual", match_mode="east",
            request_id=uuid4(),
        )
    with pytest.raises(ValueError, match="已经在德州扑克房间"):
        repo.create_chess_game("host", now=NOW)
    with pytest.raises(ValueError, match="已经在德州扑克房间"):
        repo.create_doudizhu_room("host", now=NOW)
    with pytest.raises(ValueError, match="已经在德州扑克房间"):
        repo.create_drawguess_room("host", now=NOW)


def test_active_room_restores_the_players_card_table(mahjong):
    repo, _ = mahjong
    room = repo.create_club_card_room(
        "texas", "host", NOW, room_type="casual", stake=0,
        request_id=uuid4(),
    )

    assert repo.club_active_room("host", NOW) == {
        "game": "texas", "room_id": room["id"], "phase": "waiting",
    }
    assert repo.club_active_room("viewer", NOW) is None
