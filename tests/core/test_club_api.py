import asyncio
import json
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from dzmm_bot.core.app import create_app
from dzmm_bot.core.club_api import club_card_events, club_social_events, mahjong_events
from dzmm_bot.core.schema import (
    ClubCardRoomRecord,
    ClubPlayerRecord,
    DoudizhuRoomRecord,
    DrawguessRoomRecord,
    MahjongRoomRecord,
)
from tests.core.test_mahjong_repository import NOW, mahjong, seated


def headers(uid):
    return {"Authorization": f"ClubUid {uid}"}


def test_create_list_claim_and_payload_validation(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    create = client.post(
        "/api/club/mahjong/rooms",
        headers=headers("host"),
        json={"request_id": str(uuid4()), "room_type": "casual", "match_mode": "east"},
    )
    assert create.status_code == 200
    room = create.json()
    assert "code" not in room
    listing = client.get("/api/club/mahjong/rooms", headers=headers("viewer"))
    assert listing.status_code == 200 and listing.headers["cache-control"] == "no-store"
    path = f"/api/club/mahjong/rooms/{room['id']}/actions"
    invalid = client.post(path, headers=headers("alice"), json={
        "version": 0,
        "request_id": str(uuid4()),
        "action": "claim",
        "payload": {"extra": True},
    })
    assert invalid.status_code == 422
    claimed = client.post(path, headers=headers("alice"), json={
        "version": 0,
        "request_id": str(uuid4()),
        "action": "claim",
        "payload": {},
    })
    assert claimed.status_code == 200 and claimed.json()["seat"] == 1


def test_uid_auth_and_chat_limits(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    assert client.get("/api/club/mahjong/rooms").status_code == 401
    guest = client.get("/api/club/mahjong/rooms", headers=headers("nobody"))
    assert guest.status_code == 200
    assert client.post("/api/club/mahjong/rooms", headers=headers("nobody"), json={
        "request_id": str(uuid4()), "room_type": "coin", "stake": 10, "match_mode": "east",
    }).status_code == 409
    room = client.post("/api/club/mahjong/rooms", headers=headers("host"), json={
        "request_id": str(uuid4()), "room_type": "casual", "match_mode": "east",
    }).json()
    path = f"/api/club/mahjong/rooms/{room['id']}/chat"
    payload = {"request_id": str(uuid4()), "text": "约一桌吗？"}
    first = client.post(path, headers=headers("viewer"), json=payload)
    assert first.status_code == 200
    assert client.post(path, headers=headers("viewer"), json=payload).json() == first.json()
    assert client.post(path, headers=headers("viewer"), json={
        "request_id": str(uuid4()), "text": "太快了",
    }).status_code == 429


def test_sse_snapshot_is_recipient_scoped(mahjong):
    repo, _ = mahjong
    room = repo.create_mahjong_room(
        "host", NOW, room_type="casual", match_mode="east", request_id=uuid4(),
    )

    class Request:
        async def is_disconnected(self):
            return False

    async def first():
        stream = mahjong_events(repo, __import__("uuid").UUID(room["id"]), "viewer", lambda: NOW, Request())
        event = await anext(stream)
        await stream.aclose()
        return event

    event = asyncio.run(first())
    payload = json.loads(event.split("data: ", 1)[1])
    assert payload["seat"] is None


def test_social_sse_pushes_public_channel_changes(mahjong):
    repo, _ = mahjong

    class Request:
        async def is_disconnected(self):
            return False

    async def check():
        stream = club_social_events(repo, "guest-b", lambda: NOW, Request())
        initial = json.loads((await anext(stream)).split("data: ", 1)[1])
        repo.send_club_public_message("guest-a", "实时消息", NOW)
        changed = json.loads((await asyncio.wait_for(anext(stream), 1)).split("data: ", 1)[1])
        await stream.aclose()
        return initial, changed

    initial, changed = asyncio.run(check())
    assert initial["channel"] == ""
    assert changed["channel"]


def test_card_sse_pushes_room_chat_changes(mahjong):
    repo, _ = mahjong
    room = repo.create_club_card_room(
        "texas", "host", NOW, room_type="casual", stake=0, request_id=uuid4(),
    )

    class Request:
        async def is_disconnected(self):
            return False

    async def check():
        stream = club_card_events(
            repo, "texas", __import__("uuid").UUID(room["id"]), "viewer", lambda: NOW, Request(),
        )
        await anext(stream)
        repo.club_card_chat("texas", __import__("uuid").UUID(room["id"]), "host", uuid4(), "来一局", NOW)
        event = await asyncio.wait_for(anext(stream), 1)
        await stream.aclose()
        return json.loads(event.split("data: ", 1)[1])

    changed = asyncio.run(check())
    assert changed["messages"][-1]["text"] == "来一局"


def test_daily_jobs_advance_every_club_game_deadline(mahjong, monkeypatch):
    repo, _ = mahjong
    mahjong_advanced = []
    card_advanced = []
    doudizhu_advanced = []
    drawguess_advanced = []
    monkeypatch.setattr(repo, "advance_mahjong_deadlines", mahjong_advanced.append)
    monkeypatch.setattr(repo, "advance_club_card_deadlines", card_advanced.append)
    monkeypatch.setattr(repo, "advance_doudizhu_deadlines", doudizhu_advanced.append)
    monkeypatch.setattr(repo, "advance_drawguess_deadlines", drawguess_advanced.append)
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))

    response = client.post(
        "/internal/daily-jobs/run",
        headers={"X-Core-Token": "internal"},
        json={"now": NOW.isoformat()},
    )

    assert response.status_code == 200
    assert mahjong_advanced == [NOW]
    assert card_advanced == [NOW]
    assert doudizhu_advanced == [NOW]
    assert drawguess_advanced == [NOW]


def test_guest_channel_friendship_and_direct_messages(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    first = client.post(
        "/api/club/session", headers=headers("guest-a"),
        json={"name": "路人甲", "avatar_url": "https://example.invalid/a.webp"},
    ).json()
    second = client.post(
        "/api/club/session", headers=headers("guest-b"), json={"name": "路人乙"},
    ).json()
    assert first["employee"] is False and second["employee"] is False
    initial_version = repo.club_social_version("guest-b", NOW)

    sent = client.post(
        "/api/club/channel", headers=headers("guest-a"),
        json={"request_id": str(uuid4()), "text": "有人开桌吗？"},
    )
    assert sent.status_code == 200
    assert client.get("/api/club/channel", headers=headers("guest-b")).json()[0]["text"] == "有人开桌吗？"
    channel_version = repo.club_social_version("guest-b", NOW)
    assert channel_version["channel"] != initial_version["channel"]

    request = client.post(
        "/api/club/friends", headers=headers("guest-a"), json={"player_id": second["id"]},
    )
    assert request.status_code == 200
    requested_version = repo.club_social_version("guest-b", NOW)
    assert requested_version["friends"] != channel_version["friends"]
    incoming = client.get("/api/club/friends", headers=headers("guest-b")).json()["incoming"][0]
    assert client.post(
        f"/api/club/friends/{incoming['request_id']}/accept", headers=headers("guest-b"),
    ).status_code == 200
    accepted_version = repo.club_social_version("guest-b", NOW)
    assert accepted_version["friends"] != requested_version["friends"]
    message = client.post(
        f"/api/club/friends/{second['id']}/messages", headers=headers("guest-a"),
        json={"request_id": str(uuid4()), "text": "来一局"},
    )
    assert message.status_code == 200
    assert repo.club_social_version("guest-b", NOW)["direct"]
    assert client.get(
        f"/api/club/friends/{first['id']}/messages", headers=headers("guest-b"),
    ).json()[0]["text"] == "来一局"
    profile = client.get(f"/api/club/players/{first['id']}", headers=headers("guest-b"))
    assert profile.status_code == 200
    assert profile.json()["avatar_url"] == "https://example.invalid/a.webp"
    assert profile.json()["relationship"] == "friend"


def test_card_modules_create_join_start_and_reconnect(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    for game in ("texas", "zhajinhua", "blackjack"):
        host = f"host-{game}"
        guest = f"alice-{game}"
        created = client.post(
            f"/api/club/cards/{game}/rooms", headers=headers(host),
            json={"request_id": str(uuid4()), "room_type": "casual", "stake": 0},
        )
        assert created.status_code == 200
        room = created.json()
        minimum = 2
        room = client.post(
            f"/api/club/cards/{game}/rooms/{room['id']}/actions", headers=headers(guest),
            json={"version": room["version"], "request_id": str(uuid4()), "action": "claim", "payload": {}},
        ).json()
        for uid in (host, guest)[:minimum]:
            room = client.post(
                f"/api/club/cards/{game}/rooms/{room['id']}/actions", headers=headers(uid),
                json={"version": room["version"], "request_id": str(uuid4()), "action": "ready", "payload": {}},
            ).json()
        started = client.post(
            f"/api/club/cards/{game}/rooms/{room['id']}/actions", headers=headers(host),
            json={"version": room["version"], "request_id": str(uuid4()), "action": "start", "payload": {}},
        )
        assert started.status_code == 200
        assert started.json()["phase"] in {"playing", "hand_finished"}
        reconnected = client.get(f"/api/club/cards/{game}/rooms/{room['id']}", headers=headers(host))
        assert reconnected.status_code == 200
        assert "deck" not in reconnected.json()["state"]


def test_active_room_endpoint_returns_the_players_card_table(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    room = client.post(
        "/api/club/cards/texas/rooms", headers=headers("host"),
        json={"request_id": str(uuid4()), "room_type": "casual", "stake": 0},
    ).json()

    active = client.get("/api/club/active-room", headers=headers("host"))

    assert active.status_code == 200
    assert active.json() == {
        "game": "texas", "room_id": room["id"], "phase": "waiting",
    }
    assert client.get("/api/club/active-room", headers=headers("viewer")).json() is None


def test_active_room_endpoint_covers_every_club_module(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    rooms = {
        "mahjong": repo.create_mahjong_room(
            "mahjong-host", NOW, room_type="casual", match_mode="east",
            request_id=uuid4(),
        )["id"],
        "chess": str(repo.create_chess_game("chess-host", now=NOW).id),
        "doudizhu": repo.create_doudizhu_room(
            "doudizhu-host", now=NOW, room_type="casual",
        )["id"],
        "drawguess": repo.create_drawguess_room(
            "drawguess-host", now=NOW, room_type="casual",
        )["room_id"],
    }

    for game, room_id in rooms.items():
        active = client.get(
            "/api/club/active-room", headers=headers(f"{game}-host"),
        )
        assert active.status_code == 200
        assert active.json()["game"] == game
        assert active.json()["room_id"] == room_id


def test_active_room_endpoint_ignores_finished_rooms(mahjong):
    repo, factory = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    doudizhu = repo.create_doudizhu_room("doudizhu-host", now=NOW)
    drawguess = repo.create_drawguess_room("drawguess-host", now=NOW)

    with factory.begin() as session:
        session.get(DoudizhuRoomRecord, UUID(doudizhu["id"])).phase = "finished"
        session.get(DrawguessRoomRecord, UUID(drawguess["room_id"])).phase = "finished"

    assert client.get(
        "/api/club/active-room", headers=headers("doudizhu-host"),
    ).json() is None
    assert client.get(
        "/api/club/active-room", headers=headers("drawguess-host"),
    ).json() is None


def test_active_room_endpoint_advances_finished_mahjong_hand(mahjong):
    repo, factory = mahjong
    room = seated(mahjong)
    with factory.begin() as session:
        record = session.get(MahjongRoomRecord, UUID(room["id"]))
        state = dict(record.state)
        state.update(
            phase="hand_finished",
            points=[42_000, 28_000, 19_000, 11_000],
            round_wind=27,
            hand_number=4,
            deadline=(NOW - timedelta(seconds=1)).isoformat(),
            next={"dealer_continues": False},
            result={"kind": "ron", "dealer_continues": False},
        )
        record.state = state
        record.phase = "hand_finished"
        record.deadline = NOW - timedelta(seconds=1)

    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    assert client.get(
        "/api/club/active-room", headers=headers("host"),
    ).json() is None
    with factory() as session:
        assert session.get(MahjongRoomRecord, UUID(room["id"])).phase == "match_finished"


def test_shared_room_status_covers_every_club_game_and_rejects_card_cross_game(mahjong):
    repo, factory = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    rooms = {
        "mahjong": repo.create_mahjong_room(
            "mahjong-host", NOW, room_type="casual", match_mode="east", request_id=uuid4(),
        )["id"],
        "chess": str(repo.create_chess_game("chess-host", now=NOW).id),
        "doudizhu": repo.create_doudizhu_room("doudizhu-host", now=NOW)["id"],
        "drawguess": repo.create_drawguess_room("drawguess-host", now=NOW)["room_id"],
    }
    for game in ("texas", "zhajinhua", "blackjack"):
        rooms[game] = repo.create_club_card_room(
            game, f"card-host-{game}", NOW, room_type="casual", stake=0, request_id=uuid4(),
        )["id"]

    expected_capacities = {
        "mahjong": 4, "chess": 2, "doudizhu": 3, "drawguess": 8,
        "texas": 8, "zhajinhua": 6, "blackjack": 5,
    }
    for game, room_id in rooms.items():
        response = client.get(
            f"/api/club/room-status/{game}/{room_id}", headers=headers("viewer"),
        )
        assert response.status_code == 200
        assert response.json() == {
            "game": game,
            "room_id": room_id,
            "state": "waiting",
            "label": "候场",
            "occupied": 1,
            "capacity": expected_capacities[game],
            "enterable": True,
        }

    wrong_game = client.get(
        f"/api/club/room-status/blackjack/{rooms['texas']}", headers=headers("viewer"),
    )
    assert wrong_game.status_code == 200
    assert wrong_game.json()["state"] == "dissolved"
    assert wrong_game.json()["enterable"] is False

    repo.ensure_club_player("alice", NOW)
    with factory.begin() as session:
        texas = session.get(ClubCardRoomRecord, __import__("uuid").UUID(rooms["texas"]))
        alice = session.scalar(select(ClubPlayerRecord).where(
            ClubPlayerRecord.platform_id == "alice"
        ))
        texas.phase = "playing"
        texas.seats = [*texas.seats, str(alice.id)]
    started = client.get(
        f"/api/club/room-status/texas/{rooms['texas']}", headers=headers("viewer"),
    ).json()
    assert started["state"] == "started"
    assert started["label"] == "已开始"
    assert started["occupied"] == 2


def test_presence_counts_recent_players_in_active_game_seats(mahjong):
    repo, factory = mahjong
    from dzmm_bot.core.schema import ClubPlayerRecord, DoudizhuRoomRecord

    room = repo.create_doudizhu_room("host", now=NOW)
    repo.ensure_club_player("alice", NOW)
    repo.ensure_club_player("stale", NOW - timedelta(seconds=31))
    with factory.begin() as session:
        host = session.scalar(select(ClubPlayerRecord).where(
            ClubPlayerRecord.platform_id == "host"
        ))
        alice = session.scalar(select(ClubPlayerRecord).where(
            ClubPlayerRecord.platform_id == "alice"
        ))
        active = session.get(DoudizhuRoomRecord, __import__("uuid").UUID(room["id"]))
        active.phase = "playing"
        active.seats = [str(host.id), str(alice.id), None]

    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    response = client.post("/api/club/presence", headers=headers("viewer"))

    assert response.status_code == 200
    assert response.json() == {"online": 3, "playing": 2}


def test_employee_can_claim_one_time_employment_task(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    before = client.get("/api/club/profile", headers=headers("host")).json()["balance"]
    task = next(item for item in client.get("/api/club/tasks", headers=headers("host")).json()
                if item["key"] == "employment")
    assert task["eligible"] is True and task["claimed"] is False
    claimed = client.post(
        "/api/club/tasks/claim", headers=headers("host"), json={"task_key": "employment"},
    )
    assert claimed.status_code == 200
    assert claimed.json()["balance"] == before + 20
    profile = client.get("/api/club/profile", headers=headers("host")).json()
    task_transaction = next(
        item for item in profile["recent_transactions"] if item["label"] == "任务奖励"
    )
    assert task_transaction["amount"] == 20
    assert client.post(
        "/api/club/tasks/claim", headers=headers("host"), json={"task_key": "employment"},
    ).status_code == 409


def test_guest_can_play_but_cannot_claim_employee_tasks(mahjong):
    repo, _ = mahjong
    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    tasks = client.get("/api/club/tasks", headers=headers("guest-player")).json()
    assert all(item["eligible"] is False for item in tasks)
    assert client.post(
        "/api/club/tasks/claim",
        headers=headers("guest-player"),
        json={"task_key": "employment"},
    ).status_code == 409


def test_profile_aggregates_historical_results_for_every_player(mahjong):
    repo, factory = mahjong
    from dzmm_bot.core.schema import ChessGameRecord, ClubPlayerRecord

    for uid in ("host", "alice"):
        repo.ensure_club_player(uid, NOW)
    with factory.begin() as session:
        host = session.scalar(select(ClubPlayerRecord).where(ClubPlayerRecord.platform_id == "host"))
        alice = session.scalar(select(ClubPlayerRecord).where(ClubPlayerRecord.platform_id == "alice"))
        session.add(ChessGameRecord(
            group_chat_id=None,
            inbound_message_id=None,
            creator_user_id=host.id,
            opponent_user_id=alice.id,
            red_user_id=host.id,
            black_user_id=alice.id,
            code="",
            room_type="casual",
            stake=0,
            escrowed=[False, False],
            settled=True,
            settlement={"outcomes": {"red": "win", "black": "loss"}},
            status="finished",
            created_at=NOW,
            claim_deadline=NOW,
            red_remaining_ms=0,
            black_remaining_ms=0,
            version=1,
            result="red:checkmate",
            finished_at=NOW,
            events=[],
        ))

    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    host_stats = client.get("/api/club/profile", headers=headers("host")).json()["stats"]
    alice_stats = client.get("/api/club/profile", headers=headers("alice")).json()["stats"]
    assert host_stats["total"] == {"played": 1, "wins": 1, "losses": 0, "draws": 0}
    assert alice_stats["games"]["chess"] == {"played": 1, "wins": 0, "losses": 1, "draws": 0}


def test_employment_is_once_and_other_task_triggers_are_daily(mahjong):
    repo, factory = mahjong
    from dzmm_bot.core.schema import (
        ClubPlayerRecord,
        DailyCheckinRecord,
        DarkMarketListingRecord,
        DoudizhuRoomRecord,
        DoudizhuRoundRecord,
        InboundRecord,
        RandomEventParticipantRecord,
        UserRecord,
    )

    room = repo.create_doudizhu_room("host", now=NOW)
    with factory.begin() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.platform_id == "host"))
        player = session.scalar(select(ClubPlayerRecord).where(ClubPlayerRecord.platform_id == "host"))
        room_id = __import__("uuid").UUID(room["id"])
        session.get(DoudizhuRoomRecord, room_id).round_number = 5
        completed_rounds = [
            DoudizhuRoundRecord(
                room_id=room_id,
                number=number,
                state={"phase": "finished"},
            )
            for number in range(1, 5)
        ]
        unfinished_round = DoudizhuRoundRecord(
            room_id=room_id,
            number=5,
            state={"phase": "playing"},
        )
        session.add_all([*completed_rounds, unfinished_round])
        session.flush()
        unfinished_round_id = unfinished_round.id
        session.add(DailyCheckinRecord(
            user_id=user.id, checkin_date=NOW.date(), checked_in_at=NOW,
        ))
        session.add(RandomEventParticipantRecord(
            event_id=uuid4(), user_id=user.id, role="player", rounds=1, joined_at=NOW,
        ))
        session.add_all([
            InboundRecord(
                platform_message_id=f"task-message-{index}",
                sender_platform_id="host",
                content="这是一条用于活跃任务统计的群聊消息",
                content_type="text",
                received_at=NOW,
                status="processed",
                source_type="group",
                group_chat_id=None,
                created_at=NOW,
            )
            for index in range(20)
        ])
        session.add(DarkMarketListingRecord(
            public_number=9999,
            seller_user_id=user.id,
            announcement_group_id=uuid4(),
            name="测试商品",
            purpose="任务回归测试",
            details="已成功上架",
            gender="private",
            starting_price=1,
            duration_hours_snapshot=24,
            fee_percent_snapshot=5,
            state="active",
            ends_at=NOW + timedelta(days=1),
            created_at=NOW,
        ))
        assert player.user_id == user.id

    client = TestClient(create_app(repo, "internal", clock=lambda: NOW, club_game_id="club"))
    before_completion = client.get("/api/club/tasks", headers=headers("host")).json()
    assert next(item for item in before_completion if item["key"] == "five_rounds")["eligible"] is False
    with factory.begin() as session:
        session.get(DoudizhuRoundRecord, unfinished_round_id).state = {"phase": "finished"}
    tasks = client.get("/api/club/tasks", headers=headers("host")).json()
    assert {item["key"] for item in tasks if item["eligible"]} == {
        "employment", "checkin", "random_event", "five_rounds", "activity", "dark_market",
    }
    assert next(item for item in tasks if item["key"] == "employment")["cadence"] == "once"
    assert all(item["cadence"] == "daily" for item in tasks if item["key"] != "employment")
    before = client.get("/api/club/profile", headers=headers("host")).json()["balance"]
    for task in tasks:
        response = client.post(
            "/api/club/tasks/claim",
            headers=headers("host"),
            json={"task_key": task["key"]},
        )
        assert response.status_code == 200
        duplicate = client.post(
            "/api/club/tasks/claim",
            headers=headers("host"),
            json={"task_key": task["key"]},
        )
        assert duplicate.status_code == 409
    assert client.get("/api/club/profile", headers=headers("host")).json()["balance"] == before + 36
    tomorrow = repo.club_tasks("host", NOW + timedelta(days=1))
    assert next(item for item in tomorrow if item["key"] == "employment")["claimed"] is True
    assert all(item["claimed"] is False for item in tomorrow if item["key"] != "employment")
