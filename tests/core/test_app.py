from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dzmm_bot.runtime.contracts import InboundMessage
from dzmm_bot.core.schema import (
    AIActivityEventRecord,
    DirectChatRecord,
    MemoryAssessmentGameRecord,
    MemoryAssessmentParticipantRecord,
    NumberBombGameRecord,
    NumberBombMemberRecord,
    NumberBombRoundPlayerRecord,
    NumberBombRoundRecord,
    OutboundRecord,
    RandomEventSubmissionRecord,
    TexasHoldemGameRecord,
    TexasHoldemPlayerRecord,
    UserRecord,
    WorkerCommandRecord,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


@dataclass
class AppContext:
    client: TestClient
    repository: object
    engine: object
    session_factory: object


@pytest.fixture
def app_context():
    from dzmm_bot.core.app import create_app
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(session_factory)
    from dzmm_bot.core.schema import RankRecord

    repository.list_ranks()
    with session_factory.begin() as session:
        session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 1)
        ).multiplayer_game_limit = 999
    app = create_app(repository, "test-core-token", clock=lambda: NOW)
    return AppContext(TestClient(app), repository, engine, session_factory)


@pytest.fixture
def client(app_context):
    return app_context.client


@pytest.fixture
def headers():
    return {"X-Core-Token": "test-core-token"}


@pytest.fixture
def payload():
    return {
        "platform_message_id": "platform-1",
        "sender_platform_id": "sender-1",
        "content": "hello",
        "received_at": NOW.isoformat(),
    }


def test_internal_inbound_rejects_missing_core_token(client, payload):
    assert client.post("/internal/inbound", json=payload).status_code == 401


def test_internal_inbound_is_idempotent(client, headers, payload):
    first = client.post("/internal/inbound", headers=headers, json=payload)
    second = client.post("/internal/inbound", headers=headers, json=payload)

    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert second.json()["message_id"] == first.json()["message_id"]


def test_direct_chat_sync_persists_discovered_room(app_context, headers):
    response = app_context.client.post(
        "/internal/direct-chats/sync",
        headers=headers,
        json={
            "rooms": [{"platform_user_id": "employee-1", "chatroom_id": "direct-1"}],
            "now": NOW.isoformat(),
        },
    )

    assert response.status_code == 200
    with app_context.session_factory() as session:
        record = session.scalar(select(DirectChatRecord))
    assert record is not None
    assert (record.platform_user_id, record.chatroom_id) == ("employee-1", "direct-1")


def test_direct_inbound_rooms_exclude_inactive_discovered_direct_chats(
    app_context, headers
):
    app_context.repository.upsert_direct_chats(
        [("employee-1", "direct-1"), ("employee-2", "direct-2")], NOW
    )

    response = app_context.client.get(
        "/internal/direct-inbound/rooms", headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {"chatroom_ids": []}


def test_random_event_submission_review_api_lists_and_approves(app_context, headers):
    repository = app_context.repository
    repository.create_user("submitter", "投稿人", NOW, 0)
    repository.upsert_direct_chats([("submitter", "direct-submitter")], NOW)
    draft = repository.start_random_event_submission("submitter", NOW).submission
    repository.replace_random_event_submission_content(
        draft.id,
        {
            "scene_name": "夜班文件失踪案",
            "signup_text": "夜班文件不见了，快来报名。",
            "participant_count": 2,
            "roles": [
                {"role": "调查员", "capacity": 1},
                {"role": "嫌疑人", "capacity": 1},
            ],
            "events": [{"name": "现场", "opening_text": "{调查员}开始排查。"}],
        },
        "preview",
        NOW,
    )
    pending = repository.confirm_random_event_submission("submitter", NOW)

    listed = app_context.client.get(
        "/internal/random-event-submissions?status=pending&page=1&page_size=20",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["employee_number"] == "#0001"
    assert listed.json()["items"][0]["content"]["scene_name"] == "夜班文件失踪案"

    approved = app_context.client.post(
        f"/internal/random-event-submissions/{pending.id}/approve",
        headers=headers,
        json={"reviewer": "管理员甲", "now": NOW.isoformat()},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["scene_id"] is not None


def test_direct_inbound_rooms_only_include_number_bomb_players_awaiting_a_number(
    app_context, headers
):
    with app_context.session_factory.begin() as session:
        user = UserRecord(
            platform_id="employee-1",
            display_name="员工一",
            employee_number=99,
            balance=0,
            joined_at=NOW,
        )
        game = NumberBombGameRecord(
            active_key="global",
            state="collecting",
            target_player_count=3,
            round_number=1,
            attempt_number=1,
            last_activity_at=NOW,
            created_at=NOW,
            started_at=NOW,
        )
        session.add_all([user, game])
        session.flush()
        round_record = NumberBombRoundRecord(
            game_id=game.id,
            round_number=1,
            attempt_number=1,
            punishment_type="truth",
            state="collecting",
            player_count=1,
            created_at=NOW,
        )
        session.add_all([
            DirectChatRecord(
                platform_user_id="employee-1",
                chatroom_id="direct-1",
                discovered_at=NOW,
            ),
            NumberBombMemberRecord(
                game_id=game.id,
                user_id=user.id,
                roster_order=1,
                state="current",
                queued_at=NOW,
            ),
            round_record,
        ])
        session.flush()
        session.add(NumberBombRoundPlayerRecord(
            round_id=round_record.id,
            user_id=user.id,
            display_order=1,
        ))

    response = app_context.client.get(
        "/internal/direct-inbound/rooms", headers=headers
    )
    assert response.json() == {"chatroom_ids": ["direct-1"]}

    with app_context.session_factory.begin() as session:
        session.query(NumberBombRoundPlayerRecord).update({"submitted_number": 42})
    assert app_context.client.get(
        "/internal/direct-inbound/rooms", headers=headers
    ).json() == {"chatroom_ids": []}


def test_direct_inbound_rooms_include_active_submission_and_texas_player(
    app_context, headers
):
    with app_context.session_factory.begin() as session:
        submitter = UserRecord(
            platform_id="submitter",
            display_name="投稿人",
            employee_number=98,
            balance=0,
            joined_at=NOW,
        )
        player = UserRecord(
            platform_id="texas-player",
            display_name="牌手",
            employee_number=99,
            balance=100,
            joined_at=NOW,
        )
        session.add_all([submitter, player])
        session.flush()
        game = TexasHoldemGameRecord(
            creator_user_id=player.id,
            state="preflop",
            active_key="global",
            buy_in=20,
            signup_deadline=NOW,
            created_at=NOW,
        )
        session.add(game)
        session.flush()
        session.add_all([
            DirectChatRecord(
                platform_user_id="submitter",
                chatroom_id="direct-submitter",
                discovered_at=NOW,
            ),
            DirectChatRecord(
                platform_user_id="texas-player",
                chatroom_id="direct-player",
                discovered_at=NOW,
            ),
            RandomEventSubmissionRecord(
                number=1,
                user_id=submitter.id,
                status="draft",
                current_step="scene_name",
                content={},
                created_at=NOW,
                updated_at=NOW,
                last_activity_at=NOW,
            ),
            TexasHoldemPlayerRecord(
                game_id=game.id,
                user_id=player.id,
                seat_number=1,
                original_buy_in=20,
                stack=20,
                state="active",
                joined_at=NOW,
            ),
        ])

    assert app_context.client.get(
        "/internal/direct-inbound/rooms", headers=headers
    ).json() == {"chatroom_ids": ["direct-player", "direct-submitter"]}

    with app_context.session_factory.begin() as session:
        session.query(RandomEventSubmissionRecord).update({"status": "pending"})
        session.query(TexasHoldemGameRecord).update(
            {"state": "settled", "active_key": None}
        )
    assert app_context.client.get(
        "/internal/direct-inbound/rooms", headers=headers
    ).json() == {"chatroom_ids": []}


def test_number_bomb_settings_core_api_validates_bounds(client, headers):
    assert client.get(
        "/internal/game/number-bomb/settings"
    ).status_code == 401
    initial = client.get(
        "/internal/game/number-bomb/settings", headers=headers
    )
    assert initial.json() == {
        "enabled": True,
        "signup_timeout_minutes": 2,
        "reminder_interval_seconds": 15,
    }
    response = client.patch(
        "/internal/game/number-bomb/settings",
        headers=headers,
        json={
            "enabled": False,
            "signup_timeout_minutes": 60,
            "reminder_interval_seconds": 300,
        },
    )
    assert response.json() == {
        "enabled": False,
        "signup_timeout_minutes": 60,
        "reminder_interval_seconds": 300,
    }
    for payload in (
        {"enabled": True, "signup_timeout_minutes": 0, "reminder_interval_seconds": 15},
        {"enabled": True, "signup_timeout_minutes": 61, "reminder_interval_seconds": 15},
        {"enabled": True, "signup_timeout_minutes": 2, "reminder_interval_seconds": 4},
        {"enabled": True, "signup_timeout_minutes": 2, "reminder_interval_seconds": 301},
    ):
        assert client.patch(
            "/internal/game/number-bomb/settings",
            headers=headers,
            json=payload,
        ).status_code == 422


def test_texas_holdem_settings_core_api_round_trip_and_validates_ranges(client, headers):
    assert client.get("/internal/game/texas-holdem/settings").status_code == 401
    initial = client.get(
        "/internal/game/texas-holdem/settings", headers=headers
    )
    assert initial.json() == {
        "enabled": True,
        "minimum_players": 2,
        "maximum_players": 9,
        "minimum_buy_in": 20,
        "maximum_buy_in": 200,
        "daily_start_limit": 1,
        "signup_timeout_seconds": 120,
        "action_timeout_seconds": 120,
        "small_blind_percent": 5,
        "big_blind_percent": 10,
    }
    payload = {
        "enabled": False,
        "minimum_players": 3,
        "maximum_players": 8,
        "minimum_buy_in": 30,
        "maximum_buy_in": 300,
        "daily_start_limit": 2,
        "signup_timeout_seconds": 180,
        "action_timeout_seconds": 90,
        "small_blind_percent": 4,
        "big_blind_percent": 8,
    }
    assert client.patch(
        "/internal/game/texas-holdem/settings", headers=headers, json=payload
    ).json() == payload
    invalid = {**payload, "minimum_players": 9, "maximum_players": 2}
    assert client.patch(
        "/internal/game/texas-holdem/settings", headers=headers, json=invalid
    ).status_code == 422


def test_dark_market_core_api_configures_lists_details_and_force_delists(
    app_context, headers
):
    repository = app_context.repository
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=dark-api", NOW
    )
    repository.create_user("dark-api-seller", "接口卖家", NOW, 100)
    repository.create_user("dark-api-buyer", "接口买家", NOW, 100)
    repository.upsert_direct_chats(
        [
            ("dark-api-seller", "direct-dark-api-seller"),
            ("dark-api-buyer", "direct-dark-api-buyer"),
        ],
        NOW,
    )
    initial = app_context.client.get(
        "/internal/game/dark-market/settings", headers=headers
    )
    assert initial.status_code == 200
    limits = initial.json()["rank_limits"]
    payload = {
        "enabled": True,
        "announcement_group_id": str(group.id),
        "duration_hours": 4,
        "fee_percent": 7,
        "rank_limits": [
            {"rank_id": item["rank_id"], "daily_limit": item["daily_limit"]}
            for item in limits
        ],
        "expected_version": initial.json()["version"],
    }
    updated = app_context.client.patch(
        "/internal/game/dark-market/settings", headers=headers, json=payload
    )
    assert updated.status_code == 200
    assert (updated.json()["duration_hours"], updated.json()["fee_percent"]) == (4, 7)

    assert repository.start_dark_market_draft("dark-api-seller", NOW).status == "started"
    for value in ("旧怀表", "查看时间", "停在午夜", "保密", "10"):
        repository.advance_dark_market_draft("dark-api-seller", value, NOW)
    listed = repository.confirm_dark_market_listing("dark-api-seller", UUID(int=99), NOW)
    assert listed.listing is not None
    inbound, _ = repository.accept_inbound(
        InboundMessage(
            "dark-api-bid",
            "dark-api-buyer",
            "/报价 1 20",
            NOW,
            source_type="direct",
            chatroom_id="direct-dark-api-buyer",
        )
    )
    repository.place_dark_market_bid(
        "dark-api-buyer", 1, 20, inbound.id, NOW
    )

    listings = app_context.client.get(
        "/internal/game/dark-market/listings", headers=headers
    )
    assert listings.status_code == 200
    assert listings.json()["total"] == 1
    summary = listings.json()["items"][0]
    assert summary["seller_display_name"] == "接口卖家"
    assert summary["current_bidder_display_name"] == "接口买家"
    detail = app_context.client.get(
        f"/internal/game/dark-market/listings/{listed.listing.id}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["bids"][0]["amount"] == 20
    assert detail.json()["ends_at"] is not None

    removed = app_context.client.post(
        f"/internal/game/dark-market/listings/{listed.listing.id}/force-delist",
        headers=headers,
    )
    repeated = app_context.client.post(
        f"/internal/game/dark-market/listings/{listed.listing.id}/force-delist",
        headers=headers,
    )
    assert removed.json()["status"] == "force_delisted"
    assert repeated.json()["status"] == "already_ended"


def test_dark_market_core_api_validates_settings_bounds(app_context, headers):
    initial = app_context.client.get(
        "/internal/game/dark-market/settings", headers=headers
    ).json()
    base = {
        "enabled": False,
        "announcement_group_id": None,
        "duration_hours": 3,
        "fee_percent": 5,
        "rank_limits": [
            {"rank_id": item["rank_id"], "daily_limit": item["daily_limit"]}
            for item in initial["rank_limits"]
        ],
        "expected_version": initial["version"],
    }
    for invalid in (
        {**base, "duration_hours": 0},
        {**base, "duration_hours": 25},
        {**base, "fee_percent": 0},
        {**base, "fee_percent": 101},
        {**base, "rank_limits": base["rank_limits"][:-1]},
    ):
        assert app_context.client.patch(
            "/internal/game/dark-market/settings", headers=headers, json=invalid
        ).status_code == 422


def test_red_packet_settings_core_api_validates_bounds(client, headers):
    assert client.get("/internal/game/red-packet/settings").status_code == 401
    initial = client.get(
        "/internal/game/red-packet/settings", headers=headers
    )
    assert initial.json() == {
        "expiry_minutes": 10,
        "empty_probability_percent": 5,
    }
    updated = client.patch(
        "/internal/game/red-packet/settings",
        headers=headers,
        json={"expiry_minutes": 20, "empty_probability_percent": 8},
    )
    assert updated.json() == {
        "expiry_minutes": 20,
        "empty_probability_percent": 8,
    }
    for payload in (
        {"expiry_minutes": 0, "empty_probability_percent": 5},
        {"expiry_minutes": 61, "empty_probability_percent": 5},
        {"expiry_minutes": 10, "empty_probability_percent": -1},
        {"expiry_minutes": 10, "empty_probability_percent": 31},
    ):
        assert client.patch(
            "/internal/game/red-packet/settings",
            headers=headers,
            json=payload,
        ).status_code == 422


def test_gameplay_current_hides_numbers_and_force_end_requires_exact_identity(
    app_context, headers
):
    repository = app_context.repository
    for index in range(1, 4):
        repository.create_user(f"admin-game-p{index}", f"管理玩家{index}", NOW, 0)
    repository.upsert_direct_chats(
        [
            (f"admin-game-p{index}", f"direct-admin-game-p{index}")
            for index in range(1, 4)
        ],
        NOW,
    )
    created = repository.start_number_bomb_game("admin-game-p1", NOW)
    repository.join_number_bomb_game("admin-game-p2", NOW)
    repository.join_number_bomb_game("admin-game-p3", NOW)
    repository.start_number_bomb_round("admin-game-p1", NOW)
    repository.submit_number_bomb("admin-game-p1", 73, NOW)

    current = app_context.client.get("/internal/gameplay/current", headers=headers)

    assert current.status_code == 200
    assert current.json() == {"items": [{
        "group_chat_id": "00000000-0000-0000-0000-000000000001",
        "group_name": "主群聊",
        "game_type": "number_bomb",
        "game_id": str(created.game_id),
        "state": "collecting",
        "participants": [
            {"number": 1, "display_name": "管理玩家1", "reported": True, "state": "current", "total_points": 0, "retired_at_round": None},
            {"number": 2, "display_name": "管理玩家2", "reported": False, "state": "current", "total_points": 0, "retired_at_round": None},
            {"number": 3, "display_name": "管理玩家3", "reported": False, "state": "current", "total_points": 0, "retired_at_round": None},
        ],
        "signup_deadline": None,
        "next_reminder_at": (
            NOW.astimezone(ZoneInfo("Asia/Shanghai")) + timedelta(seconds=15)
        ).isoformat(),
        "tipping_deadline": None,
        "tip_total": 0,
        "skip_enabled": False,
        "mode": "standard",
        "round_number": 1,
        "maximum_rounds": 0,
    }]}
    assert all(
        "submitted_number" not in participant
        for participant in current.json()["items"][0]["participants"]
    )

    stale = app_context.client.post(
        f"/internal/gameplay/00000000-0000-0000-0000-000000000001/blame_bomb/{created.game_id}/force-end",
        headers=headers,
    )
    ended = app_context.client.post(
        f"/internal/gameplay/00000000-0000-0000-0000-000000000001/number_bomb/{created.game_id}/force-end",
        headers=headers,
    )
    repeated = app_context.client.post(
        f"/internal/gameplay/00000000-0000-0000-0000-000000000001/number_bomb/{created.game_id}/force-end",
        headers=headers,
    )

    assert stale.status_code == 409
    assert ended.json() == {"accepted": True}
    assert repeated.status_code == 409
    assert repository.number_bomb_game_summary().state is None
    with app_context.session_factory() as session:
        game = session.get(NumberBombGameRecord, created.game_id)
        outbounds = list(session.scalars(select(OutboundRecord.text)))
        activity_events = list(session.scalars(select(AIActivityEventRecord)))
    assert game.finish_reason == "admin_forced"
    assert outbounds == ["【蹦蹦数字炸弹】管理员已强制结束当前游戏。"]
    assert activity_events == []


def test_gameplay_current_exposes_number_bomb_tournament_progress_and_points(
    app_context, headers
):
    repository = app_context.repository
    for index in range(1, 9):
        repository.create_user(
            f"admin-points-p{index}", f"积分管理玩家{index}", NOW, 0
        )
    repository.upsert_direct_chats(
        [
            (f"admin-points-p{index}", f"direct-admin-points-p{index}")
            for index in range(1, 9)
        ],
        NOW,
    )
    repository.start_number_bomb_game(
        "admin-points-p1", NOW, mode="points_tournament"
    )
    for index in range(2, 9):
        repository.join_number_bomb_game(f"admin-points-p{index}", NOW)
    repository.leave_number_bomb_game(
        "admin-points-p8", NOW + timedelta(seconds=1)
    )
    repository.submit_number_bomb("admin-points-p1", 73, NOW)

    current = app_context.client.get("/internal/gameplay/current", headers=headers)

    assert current.status_code == 200
    item = current.json()["items"][0]
    assert (
        item["mode"], item["round_number"], item["maximum_rounds"]
    ) == ("points_tournament", 1, 12)
    assert item["participants"][0] == {
        "number": 1,
        "display_name": "积分管理玩家1",
        "reported": True,
        "state": "current",
        "total_points": 0,
        "retired_at_round": None,
    }
    assert item["participants"][7] == {
        "number": 8,
        "display_name": "积分管理玩家8",
        "reported": None,
        "state": "retired",
        "total_points": 0,
        "retired_at_round": 2,
    }


def test_gameplay_current_exposes_only_public_texas_holdem_state(
    app_context, headers
):
    repository = app_context.repository
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=texas-admin", NOW
    )
    for index in range(1, 3):
        repository.create_user(
            f"texas-admin-p{index}", f"德州管理玩家{index}", NOW, 100
        )
    repository.upsert_direct_chats(
        [
            (f"texas-admin-p{index}", f"direct-texas-admin-p{index}")
            for index in range(1, 3)
        ],
        NOW,
    )
    created = repository.start_texas_holdem_signup(
        "texas-admin-p1",
        20,
        NOW,
        UUID("00000000-0000-0000-0000-000000000001"),
    )
    repository.join_texas_holdem(
        "texas-admin-p2",
        NOW,
        UUID("00000000-0000-0000-0000-000000000001"),
    )
    repository.start_texas_holdem_hand(
        "texas-admin-p1",
        NOW,
        UUID("00000000-0000-0000-0000-000000000001"),
    )

    response = app_context.client.get("/internal/gameplay/current", headers=headers)
    payload = response.json()
    game = next(item for item in payload["items"] if item["game_type"] == "texas_holdem")

    assert response.status_code == 200
    assert game["game_id"] == str(created.game_id)
    assert game["state"] == "dealing"
    assert game["board"] == []
    assert sorted(player["stack"] for player in game["participants"]) == [18, 19]
    assert sorted(
        player["total_contribution"] for player in game["participants"]
    ) == [1, 2]
    assert "hole_cards" not in repr(payload)


def test_admin_can_force_end_single_memory_assessment(app_context, headers):
    repository = app_context.repository
    repository.create_user("memory-single-player", "记忆玩家", NOW, 0)
    created = repository.start_memory_assessment_single("memory-single-player", NOW)

    response = app_context.client.post(
        f"/internal/gameplay/00000000-0000-0000-0000-000000000001/memory_single/{created.game_id}/force-end",
        headers=headers,
    )

    assert response.json() == {"accepted": True}
    assert (
        repository.active_gameplay_summary("memory-single-player", NOW).game_type
        is None
    )
    with app_context.session_factory() as session:
        game = session.get(MemoryAssessmentGameRecord, created.game_id)
        participant = session.scalar(
            select(MemoryAssessmentParticipantRecord).where(
                MemoryAssessmentParticipantRecord.game_id == created.game_id
            )
        )
        outbounds = list(session.scalars(select(OutboundRecord.text)))
        activity_events = list(session.scalars(select(AIActivityEventRecord)))
    assert game.state == "cancelled"
    assert participant.state == "cancelled"
    assert outbounds == ["【记忆考核】管理员已强制结束当前游戏。"]
    assert activity_events == []


def test_internal_inbound_executes_enabled_group_commands(app_context, headers, payload):
    payload["content"] = "/入职 小明"

    response = app_context.client.post(
        "/internal/inbound", headers=headers, json=payload
    )

    assert response.status_code == 200
    with app_context.session_factory() as session:
        reply = session.scalar(select(OutboundRecord.text))
    assert reply == (
        "小明，欢迎入职摸鱼公司。你的工号：#0001。当前余额：0 摸鱼币。"
    )


def test_undercover_settings_api_validates_roles_and_returns_public_session(client, headers):
    initial = client.get("/internal/game/undercover/settings", headers=headers)
    invalid = client.patch(
        "/internal/game/undercover/settings",
        headers=headers,
        json={
            "enabled": True,
            "vote_seconds": 120,
            "whiteboard_win_remaining": 3,
            "signup_timeout_minutes": 2,
            "roles": [
                {"player_count": 4, "civilian_count": 3, "undercover_count": 2, "whiteboard_count": 0},
                {"player_count": 5, "civilian_count": 3, "undercover_count": 1, "whiteboard_count": 1},
                {"player_count": 6, "civilian_count": 4, "undercover_count": 1, "whiteboard_count": 1},
                {"player_count": 7, "civilian_count": 4, "undercover_count": 2, "whiteboard_count": 1},
                {"player_count": 8, "civilian_count": 5, "undercover_count": 2, "whiteboard_count": 1},
            ],
        },
    )
    updated = client.patch(
        "/internal/game/undercover/settings",
        headers=headers,
        json={
            "enabled": False,
            "vote_seconds": 90,
            "whiteboard_win_remaining": 2,
            "signup_timeout_minutes": 3,
            "roles": [
                {"player_count": 4, "civilian_count": 3, "undercover_count": 1, "whiteboard_count": 0},
                {"player_count": 5, "civilian_count": 3, "undercover_count": 1, "whiteboard_count": 1},
                {"player_count": 6, "civilian_count": 4, "undercover_count": 1, "whiteboard_count": 1},
                {"player_count": 7, "civilian_count": 4, "undercover_count": 2, "whiteboard_count": 1},
                {"player_count": 8, "civilian_count": 5, "undercover_count": 2, "whiteboard_count": 1},
            ],
        },
    )
    session = client.get("/internal/game/undercover/session", headers=headers)

    assert initial.status_code == 200
    assert len(initial.json()["roles"]) == 5
    assert invalid.status_code == 422
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["vote_seconds"] == 90
    assert updated.json()["signup_timeout_minutes"] == 3
    assert session.json() == {
        "state": None,
        "target_player_count": 0,
        "player_count": 0,
        "queued_count": 0,
        "current_vote_round": 0,
        "vote_deadline": None,
    }


def test_blame_bomb_settings_and_incidents_are_managed_over_core_api(client, headers):
    initial = client.get("/internal/game/blame-bomb/settings", headers=headers)
    durations = [
        {
            "player_count": player_count,
            "minimum_seconds": player_count * 10,
            "maximum_seconds": player_count * 20,
        }
        for player_count in range(2, 11)
    ]
    invalid = client.patch(
        "/internal/game/blame-bomb/settings",
        headers=headers,
        json={
            "enabled": True,
            "signup_timeout_seconds": 60,
            "turn_timeout_seconds": 20,
            "durations": durations[:-1] + [durations[-2]],
        },
    )
    updated = client.patch(
        "/internal/game/blame-bomb/settings",
        headers=headers,
        json={
            "enabled": False,
            "signup_timeout_seconds": 90,
            "turn_timeout_seconds": 15,
            "durations": durations,
        },
    )
    created = client.post(
        "/internal/game/blame-bomb/incidents",
        headers=headers,
        json={
            "name": "咖啡事故",
            "description": "咖啡泼到了报表",
            "keywords": ["咖啡", "报表"],
        },
    )
    card_id = created.json()["id"]
    changed = client.put(
        f"/internal/game/blame-bomb/incidents/{card_id}",
        headers=headers,
        json={
            "name": "会议事故",
            "description": "会议材料发错了",
            "keywords": ["会议", "材料"],
            "enabled": False,
        },
    )
    cards = client.get(
        "/internal/game/blame-bomb/incidents?page=1&page_size=5", headers=headers
    )
    deleted = client.delete(
        f"/internal/game/blame-bomb/incidents/{card_id}", headers=headers
    )

    assert initial.status_code == 200
    assert len(initial.json()["durations"]) == 9
    assert invalid.status_code == 422
    assert updated.status_code == 200
    assert updated.json()["signup_timeout_seconds"] == 90
    assert updated.json()["durations"][0] == durations[0]
    assert created.status_code == 201
    assert changed.status_code == 200
    assert changed.json()["enabled"] is False
    assert cards.json()["items"][0]["keywords"] == ["会议", "材料"]
    assert deleted.json() == {"accepted": True}


def test_blame_bomb_session_is_public_and_admin_end_refunds(app_context, headers):
    from dzmm_bot.core.schema import RankRecord

    repository = app_context.repository
    repository.create_user("blame-api-1", "甲", NOW, 100)
    repository.create_user("blame-api-2", "乙", NOW, 100)
    repository.create_blame_incident_card(
        "咖啡事故", "咖啡泼到了报表", ["咖啡", "报表"]
    )
    with app_context.session_factory.begin() as session:
        rank = session.scalar(select(RankRecord).where(RankRecord.sort_order == 1))
        rank.multiplayer_game_limit = 3
    assert repository.start_blame_game("blame-api-1", 2, NOW).status == "signup_started"
    assert repository.join_blame_game("blame-api-2", NOW).status == "started"

    response = app_context.client.get(
        "/internal/game/blame-bomb/session", headers=headers
    )
    ended = app_context.client.post("/internal/game/blame-bomb/end", headers=headers)

    assert response.status_code == 200
    assert set(response.json()) == {
        "state",
        "target_player_count",
        "players",
        "incident",
        "current_holder",
        "temperature",
    }
    assert response.json()["state"] == "active"
    assert response.json()["incident"]["name"] == "咖啡事故"
    serialized = response.text
    assert "total_duration_seconds" not in serialized
    assert "explosion_deadline" not in serialized
    assert "turn_deadline" not in serialized
    assert ended.json() == {"accepted": True}
    assert repository.find_user("blame-api-1").balance == 100
    assert repository.find_user("blame-api-2").balance == 100


def test_ai_mention_uses_only_the_configured_trigger_prefixes(app_context, headers):
    initial = app_context.client.get(
        "/internal/game/ai-assistant/settings", headers=headers
    ).json()
    app_context.client.patch(
        "/internal/game/ai-assistant/settings",
        headers=headers,
        json={
            **initial,
            "enabled": True,
            "trigger_prefixes": ["@总监事", "/饭饭"],
            "quotas": [
                {"rank_id": quota["rank_id"], "daily_limit": 1}
                for quota in initial["quotas"]
            ],
        },
    )
    app_context.client.post(
        "/internal/inbound",
        headers=headers,
        json={
            "platform_message_id": "renamed-ai-join",
            "sender_platform_id": "renamed-ai-user",
            "content": "/入职 小明",
            "received_at": NOW.isoformat(),
        },
    )
    heartbeat = app_context.client.post(
        "/internal/heartbeat",
        headers=headers,
        json={
            "worker_id": "browser-worker",
            "login_state": "ready",
            "account_display_name": "饭饭（小狗青巫）.",
            "recorded_at": NOW.isoformat(),
        },
    )

    app_context.client.post(
        "/internal/inbound",
        headers=headers,
        json={
            "platform_message_id": "renamed-ai-account-name",
            "sender_platform_id": "renamed-ai-user",
            "content": "@饭饭（小狗青巫）. 你好，摸你屁股",
            "received_at": NOW.isoformat(),
            "chatroom_id": "room-ai",
        },
    )
    app_context.client.post(
        "/internal/inbound",
        headers=headers,
        json={
            "platform_message_id": "configured-ai-trigger",
            "sender_platform_id": "renamed-ai-user",
            "content": "/饭饭 你好，摸你屁股",
            "received_at": NOW.isoformat(),
            "chatroom_id": "room-ai",
        },
    )
    claim = app_context.client.post(
        "/internal/ai/claim",
        headers=headers,
        json={"worker_id": "ai-1", "now": NOW.isoformat(), "lease_seconds": 90},
    )

    assert heartbeat.status_code == 200
    assert claim.status_code == 200
    assert claim.json()["user_content"] == "你好，摸你屁股"


def test_ai_assistant_settings_and_lease_api_are_secret_free_and_fenced(
    app_context, headers
):
    initial = app_context.client.get(
        "/internal/game/ai-assistant/settings", headers=headers
    )

    assert initial.status_code == 200
    assert initial.json()["trigger_prefixes"] == ["@总监事"]
    assert "key" not in initial.text.lower()
    assert len(initial.json()["quotas"]) == 11
    assert initial.json()["max_response_chars"] == 10000

    invalid_trigger = app_context.client.patch(
        "/internal/game/ai-assistant/settings",
        headers=headers,
        json={**initial.json(), "trigger_prefixes": ["总监事"]},
    )
    assert invalid_trigger.status_code == 422

    configured = app_context.client.patch(
        "/internal/game/ai-assistant/settings",
        headers=headers,
        json={
            **initial.json(),
            "enabled": True,
            "persona": "群内美女总监事",
            "system_prompt": "保持简短。",
            "max_response_chars": 10000,
            "batch_message_threshold": 1,
            "quotas": [
                {"rank_id": quota["rank_id"], "daily_limit": 1}
                for quota in initial.json()["quotas"]
            ],
        },
    )
    joined = app_context.client.post(
        "/internal/inbound",
        headers=headers,
        json={
            "platform_message_id": "ai-join",
            "sender_platform_id": "ai-user",
            "content": "/入职 小明",
            "received_at": NOW.isoformat(),
        },
    )
    queued = app_context.client.post(
        "/internal/inbound",
        headers=headers,
        json={
            "platform_message_id": "ai-mention",
            "sender_platform_id": "ai-user",
            "content": "@总监事 今天适合摸鱼吗？",
            "received_at": NOW.isoformat(),
            "chatroom_id": "room-ai",
        },
    )
    claim = app_context.client.post(
        "/internal/ai/claim",
        headers=headers,
        json={"worker_id": "ai-1", "now": NOW.isoformat(), "lease_seconds": 90},
    )

    assert configured.status_code == 200
    assert configured.json()["enabled"] is True
    assert joined.status_code == 200
    assert queued.status_code == 200
    assert claim.status_code == 200
    assert claim.json()["user_content"] == "今天适合摸鱼吗？"
    assert claim.json()["history_messages"] == []
    assert claim.json()["max_response_chars"] == 10000
    assert "key" not in claim.text.lower()

    memory_claim = app_context.client.post(
        "/internal/ai/memory/claim",
        headers=headers,
        json={"worker_id": "memory-1", "now": NOW.isoformat(), "lease_seconds": 90},
    )
    assert memory_claim.status_code == 200
    assert memory_claim.json()["source_messages"] == ["@总监事 今天适合摸鱼吗？"]
    assert memory_claim.json()["source_message_count"] == 1
    assert memory_claim.json()["stable_entries"] == []
    assert memory_claim.json()["candidates"] == []
    assert "current_memory" not in memory_claim.json()
    memory_completed = app_context.client.post(
        f"/internal/ai/memory/{memory_claim.json()['user_id']}/completed",
        headers=headers,
        json={
            "worker_id": "memory-1",
            "lease_token": memory_claim.json()["lease_token"],
            "target_message_id": memory_claim.json()["target_message_id"],
            "source_message_count": memory_claim.json()["source_message_count"],
            "operations": [
                {
                    "action": "new_candidate",
                    "category": "interests",
                    "content": "持续关注摸鱼玩法",
                }
            ],
            "now": NOW.isoformat(),
        },
    )
    assert memory_completed.json() == {"accepted": True}
    memory = app_context.client.get(
        "/internal/game/users/ai-user/ai-memory", headers=headers
    )
    assert memory.json()["legacy_memory_text"] == ""

    completed = app_context.client.post(
        f"/internal/ai/{claim.json()['id']}/completed",
        headers=headers,
        json={
            "worker_id": "ai-1",
            "lease_token": claim.json()["lease_token"],
            "text": "字" * 10000,
            "now": NOW.isoformat(),
        },
    )
    stale = app_context.client.post(
        f"/internal/ai/{claim.json()['id']}/completed",
        headers=headers,
        json={
            "worker_id": "ai-1",
            "lease_token": claim.json()["lease_token"],
            "text": "不应重复发送。",
            "now": NOW.isoformat(),
        },
    )

    assert completed.json() == {"accepted": True}
    assert stale.json() == {"accepted": False}


def test_ai_impression_crud_is_categorized_pinned_and_player_scoped(
    app_context, headers
):
    app_context.repository.create_user("memory-player", "记忆玩家", NOW, 0)
    app_context.repository.create_user("other-player", "其他玩家", NOW, 0)
    app_context.repository.set_ai_player_memory(
        "memory-player", "旧的自由文本备份", NOW
    )

    created = app_context.client.post(
        "/internal/game/users/memory-player/ai-impressions",
        headers=headers,
        json={"category": "expression_style", "content": "偏好先给结论"},
    )

    assert created.status_code == 201
    assert created.json()["source"] == "admin"
    assert created.json()["pinned"] is True
    entry_id = created.json()["id"]
    memory = app_context.client.get(
        "/internal/game/users/memory-player/ai-memory", headers=headers
    ).json()
    assert memory["impressions"][0]["content"] == "偏好先给结论"
    assert memory["legacy_memory_text"] == "旧的自由文本备份"
    assert memory["activity_facts"] == []

    invalid = app_context.client.post(
        "/internal/game/users/memory-player/ai-impressions",
        headers=headers,
        json={"category": "diagnosis", "content": "焦虑"},
    )
    assert invalid.status_code == 422

    wrong_player = app_context.client.put(
        f"/internal/game/users/other-player/ai-impressions/{entry_id}",
        headers=headers,
        json={
            "category": "expression_style",
            "content": "偏好分步骤",
            "pinned": False,
        },
    )
    assert wrong_player.status_code == 404

    updated = app_context.client.put(
        f"/internal/game/users/memory-player/ai-impressions/{entry_id}",
        headers=headers,
        json={
            "category": "expression_style",
            "content": "偏好分步骤",
            "pinned": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["pinned"] is False

    cleared = app_context.client.delete(
        "/internal/game/users/memory-player/ai-memory", headers=headers
    )
    assert cleared.json() == {"accepted": True}
    after_clear = app_context.client.get(
        "/internal/game/users/memory-player/ai-memory", headers=headers
    ).json()
    assert after_clear["impressions"] == []
    assert after_clear["legacy_memory_text"] == "旧的自由文本备份"


def test_ai_knowledge_card_crud_is_typed_and_validated(app_context, headers):
    payload = {
        "topic": "economy",
        "title": "额外金币说明",
        "keywords": ["金币", "收入"],
        "content": "金额和开放状态以实时数据为准。",
        "enabled": True,
        "priority": 50,
    }
    created = app_context.client.post(
        "/internal/game/ai-knowledge-cards", headers=headers, json=payload
    )

    assert created.status_code == 200
    card_id = created.json()["id"]
    assert app_context.client.get(
        "/internal/game/ai-knowledge-cards", headers=headers
    ).json()[0]["title"] == "额外金币说明"
    updated = app_context.client.put(
        f"/internal/game/ai-knowledge-cards/{card_id}",
        headers=headers,
        json={**payload, "title": "金币说明", "keywords": ["赚钱"]},
    )
    assert updated.json()["title"] == "金币说明"
    assert app_context.client.post(
        "/internal/game/ai-knowledge-cards",
        headers=headers,
        json={**payload, "keywords": ["金币", "金币"]},
    ).status_code == 422
    assert app_context.client.delete(
        f"/internal/game/ai-knowledge-cards/{card_id}", headers=headers
    ).json() == {"accepted": True}
    assert app_context.client.delete(
        f"/internal/game/ai-knowledge-cards/{card_id}", headers=headers
    ).status_code == 404


def test_ai_assistant_settings_reject_response_limit_over_ten_thousand(client, headers):
    initial = client.get("/internal/game/ai-assistant/settings", headers=headers).json()
    payload = {
        **initial,
        "max_response_chars": 10001,
        "quotas": [
            {"rank_id": quota["rank_id"], "daily_limit": quota["daily_limit"]}
            for quota in initial["quotas"]
        ],
    }

    response = client.patch(
        "/internal/game/ai-assistant/settings", headers=headers, json=payload
    )

    assert response.status_code == 422


def test_ai_assistant_settings_accept_long_prompt_configuration(client, headers):
    initial = client.get("/internal/game/ai-assistant/settings", headers=headers)
    payload = initial.json()
    payload.update(
        persona="人设" * 3000,
        system_prompt="系统提示词" * 3000,
        extraction_prompt="提炼规则" * 3000,
        quotas=[
            {"rank_id": quota["rank_id"], "daily_limit": quota["daily_limit"]}
            for quota in payload["quotas"]
        ],
    )

    response = client.patch(
        "/internal/game/ai-assistant/settings", headers=headers, json=payload
    )

    assert response.status_code == 200
    assert response.json()["system_prompt"] == payload["system_prompt"]


def test_heartbeat_response_uses_beijing_time(client, headers):
    response = client.post(
        "/internal/heartbeat",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "login_state": "ready",
            "recorded_at": NOW.isoformat(),
        },
    )

    assert response.status_code == 200
    assert response.json()["recorded_at"] == "2026-08-04T20:00:00+08:00"


def test_manual_login_api_allows_one_operator_and_any_cancellation(client, headers):
    started = client.post(
        "/internal/admin/login/start",
        headers=headers,
        json={"operator_id": "alice-id", "operator_name": "alice"},
    )
    blocked = client.post(
        "/internal/admin/login/start",
        headers=headers,
        json={"operator_id": "bob-id", "operator_name": "bob"},
    )
    cancelled = client.post("/internal/admin/login/cancel", headers=headers)

    assert started.status_code == 200
    assert started.json()["operator_name"] == "alice"
    assert blocked.status_code == 409
    assert cancelled.status_code == 200
    assert client.get("/internal/admin/login/lease", headers=headers).json() is None


def test_game_management_lists_commands_employees_and_shop_items(client, headers):
    commands = client.get("/internal/game/commands", headers=headers)
    disabled = client.patch(
        "/internal/game/commands",
        headers=headers,
        json={"command": "/打卡", "enabled": False},
    )
    employees = client.get("/internal/game/users", headers=headers)
    created_item = client.post(
        "/internal/game/items",
        headers=headers,
        json={"name": "工位午睡券", "description": "眯十分钟。", "price": 5, "stock": 3},
    )
    items = client.get("/internal/game/items", headers=headers)

    assert commands.status_code == 200
    assert {record["command"] for record in commands.json()} == {
            "/入职", "/我的物品", "/购买", "/使用", "/邀请参与", "/取消使用", "/同意使用", "/拒绝使用", "/打卡", "/余额", "/修改名称", "/编辑档案", "/编辑档案形象", "/我的档案", "/发奖金", "/发红包", "/抢红包", "/打赏", "/我", "/商店", "/帮助", "/当前游戏", "/加入", "/退出", "/开始", "/跳过", "/摸鱼躲猫猫", "/记忆考核", "/继续", "/收手", "/投降", "/谁是卧底", "/开始投票", "/投票", "/退出谁是卧底", "/结束游戏", "/甩锅游戏", "/甩锅", "/退出甩锅", "/蹦蹦数字炸弹", "/报数", "/德州扑克", "/看牌", "/过牌", "/跟注", "/加注", "/全下", "/弃牌", "/上架暗网", "/取消上架", "/确认", "/报价", "/公开", "/不公开", "/查看暗网", "/确认收货", "/投诉", "/部门", "/部门人数", "/我的部门人数", "/加入部门", "/切换部门", "/部门申请列表", "/同意部门", "/全部同意部门", "/拒绝部门", "/全部拒绝部门", "/职位", "/晋升", "/晋升申请列表", "/同意", "/全部同意", "/拒绝", "/全部拒绝", "/投稿", "/我的投稿", "/撤回投稿", "/上一步", "/取消投稿", "/确认取消投稿", "/确认投稿", "/继续添加", "/事件完成", "/修改身份", "/删除身份", "/修改事件", "/删除事件"
            }
    command_records = {record["command"]: record for record in commands.json()}
    for command in ("/部门人数", "/我的部门人数"):
        assert {template["scenario"] for template in command_records[command]["templates"]} == {
            "shown",
            "not_joined",
        }
    assert {template["scenario"] for template in command_records["/编辑档案"]["templates"]} == {
        "usage", "not_joined", "too_long", "unchanged",
        "insufficient_balance", "insufficient_labor", "updated",
    }
    assert {template["scenario"] for template in command_records["/我的档案"]["templates"]} == {
        "not_joined", "empty", "shown",
    }
    assert disabled.json()["enabled"] is False
    assert employees.json() == {
        "items": [],
        "page": 1,
        "page_size": 20,
        "total": 0,
        "pages": 0,
    }
    assert created_item.status_code == 201
    item_page = items.json()
    assert item_page["total"] == 23
    assert item_page["pages"] == 2
    assert item_page["items"][0] == {
        "public_number": 23,
        "name": "工位午睡券",
        "description": "眯十分钟。",
        "price": 5,
        "stock": 3,
        "unlimited_stock": False,
        "system_key": None,
        "effect_type": None,
        "minimum_rank_order": None,
        "enabled": True,
    }


def test_rank_department_and_promotion_management_endpoints(app_context, client, headers):
    ranks = client.get("/internal/game/ranks", headers=headers)
    departments = client.get(
        "/internal/game/departments?page=1&page_size=20", headers=headers
    )
    created_department = client.post(
        "/internal/game/departments",
        headers=headers,
        json={"name": "运营部", "description": "负责运营。"},
    )
    app_context.repository.create_user("u1", "小明", NOW, 80)
    requested = app_context.repository.request_promotion("u1", NOW)
    requested_department = app_context.repository.request_department_change(
        "u1", "核心技术部", NOW
    )
    promotions = client.get(
        "/internal/game/promotions?state=pending&page=1&page_size=20",
        headers=headers,
    )
    department_requests = client.get(
        "/internal/game/department-requests?state=pending&page=1&page_size=20",
        headers=headers,
    )
    board = client.post(
        "/internal/game/users/u1/board-membership",
        headers=headers,
        json={"member": True},
    )

    assert ranks.status_code == 200
    assert ranks.json()[0]["name"] == "实习生"
    assert departments.status_code == 200
    assert departments.json()["items"][0]["name"] == "未分配部门"
    assert created_department.status_code == 201
    assert created_department.json()["name"] == "运营部"
    assert requested.status == "requested"
    assert promotions.status_code == 200
    assert promotions.json()["items"][0]["number"] == requested.number
    assert department_requests.status_code == 200
    assert department_requests.json()["items"][0]["number"] == requested_department.number
    assert department_requests.json()["items"][0]["target_department_name"] == "核心技术部"
    assert board.status_code == 200
    assert board.json()["rank"]["name"] == "核心董事会"


def test_game_management_returns_paginated_employees_and_items(
    app_context, client, headers
):
    for index in range(21):
        app_context.repository.create_user(
            f"u-{index}", f"员工{index}", NOW + timedelta(minutes=index), 0
        )
        app_context.repository.add_item(f"物品{index}", "说明", index, 1)

    employees = client.get("/internal/game/users?page=2&page_size=20", headers=headers)
    items = client.get("/internal/game/items?page=3&page_size=20", headers=headers)

    assert employees.status_code == 200
    assert employees.json()["page"] == 2
    assert employees.json()["page_size"] == 20
    assert employees.json()["total"] == 21
    assert employees.json()["pages"] == 2
    assert len(employees.json()["items"]) == 1
    assert employees.json()["items"][0]["employee_number"] == 1
    assert items.status_code == 200
    assert items.json()["total"] == 43
    assert items.json()["pages"] == 3
    assert len(items.json()["items"]) == 3


def test_shop_admin_activity_and_control_endpoints(app_context, headers):
    activity = app_context.client.get(
        "/internal/game/shop/activity?limit=20", headers=headers
    )
    retried = app_context.client.post(
        "/internal/game/shop/scene-jobs/00000000-0000-0000-0000-000000000099/retry",
        headers=headers,
    )
    ended = app_context.client.post(
        "/internal/game/shop/common-states/00000000-0000-0000-0000-000000000099/end",
        headers=headers,
    )

    assert activity.status_code == 200
    assert activity.json() == {
        "purchases": [],
        "uses": [],
        "consents": [],
        "scene_jobs": [],
        "common_states": [],
    }
    assert retried.json() == {"accepted": False}
    assert ended.json() == {"accepted": False}


def test_employee_balance_ledger_endpoint_is_paginated_and_protected(
    app_context, client, headers
):
    user, _ = app_context.repository.create_user("ledger-api", "流水员工", NOW, 10)
    app_context.repository.record_balance_change(
        user.id, -2, "shop", NOW + timedelta(minutes=1)
    )
    app_context.repository.record_balance_change(
        user.id, 5, "checkin", NOW + timedelta(minutes=2)
    )

    response = client.get(
        "/internal/game/users/ledger-api/balance-transactions?page=1&page_size=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "platform_id": "ledger-api",
        "display_name": "流水员工",
        "current_balance": 13,
        "items": [
            {
                "id": response.json()["items"][0]["id"],
                "amount": 5,
                "source": "checkin",
                "source_label": "每日打卡",
                "occurred_at": "2026-08-04T20:02:00+08:00",
                "balance_after": 13,
            }
        ],
        "page": 1,
        "page_size": 1,
        "total": 3,
        "pages": 3,
    }
    assert client.get(
        "/internal/game/users/ledger-api/balance-transactions"
    ).status_code == 401
    assert client.get(
        "/internal/game/users/missing/balance-transactions", headers=headers
    ).status_code == 404
    assert client.get(
        "/internal/game/users/ledger-api/balance-transactions?page=0", headers=headers
    ).status_code == 422


def test_employee_group_messages_can_be_filtered_by_group(
    app_context, client, headers
):
    first = app_context.repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=history-a", NOW
    )
    second = app_context.repository.create_group_chat(
        "乙群",
        "https://www.aikda.com/chat?c=history-b",
        True,
        True,
        True,
        True,
        NOW,
    )
    app_context.repository.create_user("history-user", "历史员工", NOW, 0)
    for group, message_id, content in (
        (first, "history-message-a", "甲群消息"),
        (second, "history-message-b", "乙群消息"),
    ):
        app_context.repository.accept_inbound(
            InboundMessage(
                message_id,
                "history-user",
                content,
                NOW,
                chatroom_id=group.chatroom_id,
            ),
            group_chat_id=group.id,
        )

    all_messages = client.get(
        "/internal/game/users/history-user/group-messages", headers=headers
    )
    filtered = client.get(
        "/internal/game/users/history-user/group-messages",
        params={"group_chat_id": second.id},
        headers=headers,
    )

    assert all_messages.status_code == 200
    assert {item["group_name"] for item in all_messages.json()["items"]} == {
        "主群聊",
        "乙群",
    }
    assert [item["content"] for item in filtered.json()["items"]] == ["乙群消息"]


def test_game_settings_can_be_read_and_updated(client, headers):
    initial = client.get("/internal/game/settings", headers=headers)
    updated = client.patch(
        "/internal/game/settings",
        headers=headers,
        json={
            "currency_name": "工分",
            "onboarding_bonus": 3,
            "checkin_reward": 7,
            "weekly_attendance_reward": 9,
        },
    )

    assert initial.json() == {
        "currency_name": "摸鱼币",
        "onboarding_bonus": 0,
        "checkin_reward": 5,
        "weekly_attendance_reward": 5,
        "reset_time_label": "北京时间 00:00",
    }
    assert updated.json() == {
        "currency_name": "工分",
        "onboarding_bonus": 3,
        "checkin_reward": 7,
        "weekly_attendance_reward": 9,
        "reset_time_label": "北京时间 00:00",
    }


def test_activity_settings_can_be_read_and_updated(client, headers):
    initial = client.get("/internal/game/activity-settings", headers=headers)
    updated = client.patch(
        "/internal/game/activity-settings",
        headers=headers,
        json={
            "rules": [
                {
                    "level": level,
                    "character_threshold": level * 10,
                    "reward": level,
                }
                for level in range(1, 11)
            ],
            "report_times": ["09:30", "18:00"],
        },
    )

    assert initial.status_code == 200
    assert initial.json()["report_times"] == ["12:00", "16:00", "20:00", "23:59"]
    assert updated.status_code == 200
    assert updated.json()["report_times"] == ["09:30", "18:00"]


def test_hide_and_seek_settings_and_scenes_are_managed_over_core_api(client, headers):
    settings = client.get("/internal/game/hide-and-seek/settings", headers=headers)
    updated = client.patch(
        "/internal/game/hide-and-seek/settings",
        headers=headers,
        json={
            "enabled": True,
            "entry_fee": 2,
            "win_reward": 5,
            "daily_limit": 3,
            "selection_timeout_minutes": 2,
        },
    )
    created = client.post(
        "/internal/game/hide-and-seek/scenes",
        headers=headers,
        json={"name": "打印区"},
    )
    scenes = client.get(
        "/internal/game/hide-and-seek/scenes?page=1&page_size=5", headers=headers
    )

    assert settings.status_code == 200
    assert settings.json()["daily_limit"] == 2
    assert updated.status_code == 200
    assert updated.json()["entry_fee"] == 2
    assert created.status_code == 201
    assert scenes.json()["total"] == 11


def test_memory_assessment_settings_are_managed_over_core_api(client, headers):
    initial = client.get("/internal/game/memory-assessment/settings", headers=headers)
    updated = client.patch(
        "/internal/game/memory-assessment/settings",
        headers=headers,
        json={
            "enabled": True,
            "single_daily_limit": 1,
            "single_recall_seconds": 4,
            "duel_recall_seconds": 5,
            "duel_difficulty_level": 5,
            "duel_base_pool": 6,
            "duel_wrong_freeze": 2,
            "duel_wrong_limit": 8,
            "duel_answer_timeout_minutes": 9,
            "duel_signup_timeout_minutes": 4,
            "character_set": "ABC123",
            "levels": [
                {"level": level, "answer_length": level * 2 + 3, "reward": level}
                for level in range(1, 6)
            ],
        },
    )

    assert initial.status_code == 200
    assert initial.json()["single_recall_seconds"] == 3
    assert updated.status_code == 200
    assert updated.json()["duel_base_pool"] == 6
    assert updated.json()["duel_signup_timeout_minutes"] == 4
    assert updated.json()["levels"][4] == {
        "level": 5,
        "answer_length": 13,
        "reward": 5,
    }


def test_daily_jobs_require_the_core_token(client, headers):
    assert client.post("/internal/daily-jobs/run", json={"now": NOW.isoformat()}).status_code == 401

    response = client.post(
        "/internal/daily-jobs/run", headers=headers, json={"now": NOW.isoformat()}
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}


def test_game_commands_list_templates_and_update_a_valid_template(client, headers):
    commands = client.get("/internal/game/commands", headers=headers).json()
    balance = next(command for command in commands if command["command"] == "/余额")

    response = client.patch(
        "/internal/game/command-templates",
        headers=headers,
        json={
            "command": "/余额",
            "scenario": "shown",
            "template": "{昵称}：{余额}",
        },
    )

    assert balance["templates"] == [
        {
            "scenario": "shown",
            "label": "查询成功",
            "template": "{昵称}，当前余额：{余额} {货币}。",
            "variables": ["{昵称}", "{余额}", "{货币}", "{日期}"],
        },
        {
            "scenario": "not_joined",
            "label": "未入职",
            "template": "请先用 /入职 名字 加入摸鱼公司。",
            "variables": ["{日期}"],
        },
    ]
    assert response.status_code == 200
    assert response.json()["template"] == "{昵称}：{余额}"


def test_game_command_template_rejects_an_unsupported_variable(client, headers):
    response = client.patch(
        "/internal/game/command-templates",
        headers=headers,
        json={
            "command": "/余额",
            "scenario": "shown",
            "template": "{商店列表}",
        },
    )

    assert response.status_code == 422


def test_personal_profile_settings_and_admin_profile_endpoints(app_context, headers):
    app_context.repository.create_user("profile-api", "档案员工", NOW, 30)

    initial = app_context.client.get(
        "/internal/game/profile-settings", headers=headers
    )
    updated = app_context.client.patch(
        "/internal/game/profile-settings",
        headers=headers,
        json={"edit_cost": 12, "shared_labor": 8, "version": 0},
    )
    shown = app_context.client.get(
        "/internal/game/users/profile-api/profile", headers=headers
    )
    saved = app_context.client.put(
        "/internal/game/users/profile-api/profile",
        headers=headers,
        json={"profile_text": "管理员填写"},
    )
    cleared = app_context.client.put(
        "/internal/game/users/profile-api/profile",
        headers=headers,
        json={"profile_text": ""},
    )

    assert initial.json() == {"edit_cost": 10, "shared_labor": 5, "version": 0}
    assert updated.json() == {"edit_cost": 12, "shared_labor": 8, "version": 1}
    assert shown.json()["profile_text"] == ""
    assert saved.json()["profile_text"] == "管理员填写"
    assert cleared.json()["profile_text"] == ""
    assert app_context.repository.find_user("profile-api").balance == 30
    assert app_context.repository.get_profile_settings().shared_labor == 8


def test_personal_profile_admin_endpoints_validate_conflicts_and_limits(app_context, headers):
    app_context.repository.create_user("profile-api", "档案员工", NOW, 30)
    first = app_context.client.patch(
        "/internal/game/profile-settings",
        headers=headers,
        json={"edit_cost": 0, "shared_labor": 99999, "version": 0},
    )
    stale = app_context.client.patch(
        "/internal/game/profile-settings",
        headers=headers,
        json={"edit_cost": 1, "shared_labor": 1, "version": 0},
    )
    too_long = app_context.client.put(
        "/internal/game/users/profile-api/profile",
        headers=headers,
        json={"profile_text": "字" * 801},
    )
    missing = app_context.client.get(
        "/internal/game/users/missing/profile", headers=headers
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert too_long.status_code == 422
    assert missing.status_code == 404


def test_core_server_factory_enforces_local_settings_port(app_context):
    from dzmm_bot.core.app import create_server
    from dzmm_bot.runtime.settings import Settings

    settings = Settings(
        database_url="postgresql+psycopg://dzmm@localhost/dzmm",
        core_token="test-core-token",
        admin_token=None,
        browser_profile=Path("/var/lib/dzmm/browser"),
        login_url=None,
        core_api_port=18120,
        browser_cdp_port=19222,
        admin_web_port=18090,
        novnc_port=16080,
        chat_url="https://www.aikda.com/chat?c=primary-room&utm_source=env",
    )

    server = create_server(app_context.repository, settings)

    assert server.config.host == "127.0.0.1"
    assert server.config.port == settings.core_api_port
    assert app_context.repository.group_chat_bootstrap_ready() is True


def test_core_server_health_is_degraded_without_primary_group(app_context):
    from dzmm_bot.core.app import create_server
    from dzmm_bot.runtime.settings import Settings

    settings = Settings(
        database_url="postgresql+psycopg://dzmm@localhost/dzmm",
        core_token="test-core-token",
        admin_token=None,
        browser_profile=Path("/var/lib/dzmm/browser"),
        login_url=None,
        core_api_port=18120,
        browser_cdp_port=19222,
        admin_web_port=18090,
        novnc_port=16080,
        chat_url=None,
    )

    server = create_server(app_context.repository, settings)
    response = TestClient(server.config.app).get("/healthz")

    assert response.status_code == 503
    assert response.json()["database_available"] is True


def test_group_chat_crud_targets_and_runtime_api(app_context, headers):
    primary = app_context.repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", NOW
    )
    created = app_context.client.post(
        "/internal/group-chats",
        headers=headers,
        json={
            "name": "第二群",
            "chat_url": "https://www.aikda.com/chat?c=group-2&utm_source=admin",
            "listening_enabled": True,
            "games_enabled": False,
            "enabled_game_types": ["number_bomb"],
            "random_events_enabled": True,
            "announcements_enabled": False,
            "now": NOW.isoformat(),
        },
    )

    assert created.status_code == 201
    second = created.json()
    assert second["chat_url"] == "https://www.aikda.com/chat?c=group-2"
    assert second.get("enabled_game_types") == ["number_bomb"]
    assert second["runtime"]["connection_state"] == "pending"

    targets = app_context.client.get(
        "/internal/group-chats/targets", headers=headers
    )
    assert {target["chatroom_id"] for target in targets.json()} == {
        "group-main",
        "group-2",
    }
    runtime = app_context.client.post(
        "/internal/group-chats/runtime",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "statuses": [
                {
                    "group_chat_id": second["id"],
                    "connection_state": "connected",
                    "last_connected_at": NOW.isoformat(),
                }
            ],
            "now": NOW.isoformat(),
        },
    )
    listed = app_context.client.get("/internal/group-chats", headers=headers)

    assert runtime.json() == {"accepted": True}
    listed_by_id = {item["id"]: item for item in listed.json()}
    assert listed_by_id[second["id"]]["runtime"]["connection_state"] == "connected"
    assert listed_by_id[str(primary.id)]["name"] == "主群聊"


def test_database_backed_identifiers_reject_more_than_255_characters(
    client, headers, payload
):
    oversized = "x" * 256
    payload["platform_message_id"] = oversized

    inbound = client.post("/internal/inbound", headers=headers, json=payload)
    heartbeat = client.post(
        "/internal/heartbeat",
        headers=headers,
        json={
            "worker_id": oversized,
            "login_state": "ready",
            "recorded_at": NOW.isoformat(),
        },
    )
    sent = client.post(
        "/internal/outbound/00000000-0000-0000-0000-000000000000/sent",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "lease_token": "00000000-0000-0000-0000-000000000000",
            "platform_sent_id": oversized,
            "now": NOW.isoformat(),
        },
    )

    assert inbound.status_code == 422
    assert heartbeat.status_code == 422
    assert sent.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/internal/outbound/claim"),
        ("post", "/internal/outbound/00000000-0000-0000-0000-000000000000/sent"),
        ("post", "/internal/outbound/00000000-0000-0000-0000-000000000000/failed"),
        ("post", "/internal/outbound/00000000-0000-0000-0000-000000000000/retry"),
        ("post", "/internal/heartbeat"),
        ("get", "/internal/login-state"),
        ("get", "/internal/status"),
        ("get", "/internal/game/activity-settings"),
        ("patch", "/internal/game/activity-settings"),
        ("patch", "/internal/game/command-templates"),
        ("post", "/internal/daily-jobs/run"),
        ("post", "/internal/worker-commands"),
        ("post", "/internal/worker-commands/claim"),
        (
            "post",
            "/internal/worker-commands/00000000-0000-0000-0000-000000000000/complete",
        ),
    ],
)
def test_every_internal_route_requires_core_token(client, method, path):
    assert client.request(method, path, json={}).status_code == 401


def test_outbound_claim_and_fenced_sent_acknowledgement(
    app_context, headers, payload
):
    inbound = app_context.client.post(
        "/internal/inbound", headers=headers, json=payload
    ).json()
    outbound = app_context.repository.enqueue_outbound(
        inbound["message_id"], "reply"
    )

    first = app_context.client.post(
        "/internal/outbound/claim",
        headers=headers,
        json={"worker_id": "worker-a", "now": NOW.isoformat(), "lease_seconds": 30},
    ).json()
    second = app_context.client.post(
        "/internal/outbound/claim",
        headers=headers,
        json={
            "worker_id": "worker-b",
            "now": (NOW + timedelta(seconds=31)).isoformat(),
            "lease_seconds": 30,
        },
    ).json()

    stale = app_context.client.post(
        f"/internal/outbound/{outbound.id}/sent",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "lease_token": first["lease_token"],
            "platform_sent_id": "stale-send",
            "now": (NOW + timedelta(seconds=32)).isoformat(),
        },
    )
    with app_context.session_factory() as session:
        persisted_after_stale = session.scalar(
            select(OutboundRecord).where(OutboundRecord.id == outbound.id)
        )
        assert persisted_after_stale.status == "leased"
        assert persisted_after_stale.lease_worker_id == "worker-b"
        assert persisted_after_stale.lease_token == UUID(second["lease_token"])
        assert persisted_after_stale.platform_sent_id is None

    fresh = app_context.client.post(
        f"/internal/outbound/{outbound.id}/sent",
        headers=headers,
        json={
            "worker_id": "worker-b",
            "lease_token": second["lease_token"],
            "platform_sent_id": "sent-1",
            "now": (NOW + timedelta(seconds=32)).isoformat(),
        },
    )

    assert first["id"] == str(outbound.id)
    assert (first["content_type"], first["image_url"], first["image_alt"]) == (
        "text", None, None,
    )
    assert first["recall_after_seconds"] is None
    assert second["id"] == str(outbound.id)
    assert stale.status_code == 200
    assert stale.json() == {"accepted": False}
    assert fresh.json() == {"accepted": True}
    assert (
        app_context.client.post(
            "/internal/outbound/claim",
            headers=headers,
            json={
                "worker_id": "worker-c",
                "now": (NOW + timedelta(seconds=63)).isoformat(),
                "lease_seconds": 30,
            },
        ).json()
        is None
    )


def test_image_outbound_claim_serializes_image_content(app_context, headers, payload):
    inbound = app_context.client.post(
        "/internal/inbound", headers=headers, json=payload
    ).json()
    outbound = app_context.repository.enqueue_image_outbound(
        inbound["message_id"], "https://cdn.example.com/profile.png", image_alt="档案形象"
    )

    claimed = app_context.client.post(
        "/internal/outbound/claim",
        headers=headers,
        json={"worker_id": "worker-a", "now": NOW.isoformat(), "lease_seconds": 30},
    ).json()

    assert claimed["id"] == str(outbound.id)
    assert (claimed["content_type"], claimed["text"], claimed["image_url"], claimed["image_alt"]) == (
        "image", "", "https://cdn.example.com/profile.png", "档案形象",
    )


def test_profile_image_upload_internal_api_claims_and_completes(app_context, headers):
    app_context.repository.create_user("upload-player", "上传玩家", NOW, 30)
    app_context.repository.set_personal_profile_by_admin("upload-player", "个人介绍")
    created = app_context.client.post(
        "/internal/game/users/upload-player/profile-image-uploads",
        headers=headers,
        json={
            "temp_path": "/tmp/profile.png", "original_filename": "profile.png",
            "mime_type": "image/png", "now": NOW.isoformat(),
        },
    )
    task_id = created.json()["id"]

    claimed = app_context.client.post(
        "/internal/profile-image-uploads/claim",
        headers=headers,
        json={"worker_id": "worker-a", "now": NOW.isoformat(), "lease_seconds": 30},
    )
    claim = claimed.json()
    completed = app_context.client.post(
            f"/internal/profile-image-uploads/{task_id}/completed",
        headers=headers,
        json={
            "worker_id": "worker-a", "lease_token": claim["lease_token"],
            "result_url": "https://cdn.example.com/profile.png",
            "now": NOW.isoformat(),
        },
    )

    assert claimed.status_code == 200
    assert created.json()["status"] == "pending"
    assert (claim["id"], claim["temp_path"], claim["mime_type"]) == (
        task_id, "/tmp/profile.png", "image/png",
    )
    assert completed.json() == {"accepted": True}
    status_response = app_context.client.get(
        f"/internal/profile-image-uploads/{task_id}", headers=headers
    )
    assert status_response.json()["status"] == "completed"
    assert app_context.repository.find_user("upload-player").profile_image_url == (
        "https://cdn.example.com/profile.png"
    )
    cleanup_claim = app_context.client.post(
        "/internal/profile-image-cleanups/claim",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "now": (NOW + timedelta(seconds=1)).isoformat(),
            "lease_seconds": 30,
        },
    ).json()
    cleaned = app_context.client.post(
        f"/internal/profile-image-cleanups/{task_id}/completed",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "lease_token": cleanup_claim["lease_token"],
            "now": (NOW + timedelta(seconds=2)).isoformat(),
        },
    )
    assert cleanup_claim["temp_path"] == "/tmp/profile.png"
    assert cleaned.json() == {"accepted": True}
    assert app_context.repository.get_profile_image_upload(task_id).temp_path == ""


def test_outbound_sent_requires_all_fencing_fields(client, headers):
    response = client.post(
        "/internal/outbound/00000000-0000-0000-0000-000000000000/sent",
        headers=headers,
        json={"platform_sent_id": "sent-1"},
    )

    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} == {
        "worker_id",
        "lease_token",
        "now",
    }


def test_outbound_failed_releases_the_current_lease(app_context, headers, payload):
    inbound = app_context.client.post(
        "/internal/inbound", headers=headers, json=payload
    ).json()
    outbound = app_context.repository.enqueue_outbound(inbound["message_id"], "reply")
    claim = app_context.client.post(
        "/internal/outbound/claim",
        headers=headers,
        json={"worker_id": "worker-a", "now": NOW.isoformat(), "lease_seconds": 30},
    ).json()

    response = app_context.client.post(
        f"/internal/outbound/{outbound.id}/failed",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "lease_token": claim["lease_token"],
            "now": NOW.isoformat(),
        },
    )

    assert response.json() == {"accepted": True}
    with app_context.session_factory() as session:
        assert session.get(OutboundRecord, outbound.id).status == "failed"


def test_outbound_retry_releases_the_current_lease_for_immediate_reclaim(
    app_context, headers, payload
):
    inbound = app_context.client.post(
        "/internal/inbound", headers=headers, json=payload
    ).json()
    outbound = app_context.repository.enqueue_outbound(inbound["message_id"], "reply")
    claim = app_context.client.post(
        "/internal/outbound/claim",
        headers=headers,
        json={"worker_id": "worker-a", "now": NOW.isoformat(), "lease_seconds": 30},
    ).json()

    response = app_context.client.post(
        f"/internal/outbound/{outbound.id}/retry",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "lease_token": claim["lease_token"],
            "now": NOW.isoformat(),
        },
    )
    retried = app_context.client.post(
        "/internal/outbound/claim",
        headers=headers,
        json={"worker_id": "worker-b", "now": NOW.isoformat(), "lease_seconds": 30},
    ).json()

    assert response.json() == {"accepted": True}
    assert retried["id"] == str(outbound.id)


def test_heartbeat_updates_login_state_and_health_age(app_context, headers):
    before = app_context.client.get("/healthz")
    heartbeat = app_context.client.post(
        "/internal/heartbeat",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "login_state": "ready",
            "listening": False,
            "bot_delivery_state": "captcha_required",
            "bot_delivery_error": "captcha_required",
            "recorded_at": (NOW - timedelta(seconds=12)).isoformat(),
        },
    )
    login_state = app_context.client.get(
        "/internal/login-state", headers=headers
    )
    after = app_context.client.get("/healthz")

    assert before.json() == {
        "database_available": True,
        "latest_worker_heartbeat_age_seconds": None,
    }
    assert heartbeat.status_code == 200
    assert heartbeat.json() == {
        "worker_id": "worker-a",
        "login_state": "ready",
        "listening": False,
        "listening_desired": True,
        "bot_delivery_state": "captcha_required",
        "bot_delivery_error": "captcha_required",
        "recorded_at": "2026-08-04T19:59:48+08:00",
    }
    assert login_state.json() == heartbeat.json()
    assert after.json() == {
        "database_available": True,
        "latest_worker_heartbeat_age_seconds": 12.0,
    }
    assert "token" not in after.text.lower()


def test_health_reports_database_unavailability_without_details(app_context):
    app_context.engine.dispose()

    response = app_context.client.get("/healthz")

    assert response.status_code == 503
    assert response.json() == {
        "database_available": False,
        "latest_worker_heartbeat_age_seconds": None,
    }


def test_internal_status_returns_real_queue_counts_and_latest_heartbeat(
    app_context, headers, payload
):
    inbound = app_context.client.post(
        "/internal/inbound", headers=headers, json=payload
    ).json()
    app_context.repository.enqueue_outbound(inbound["message_id"], "reply")
    app_context.client.post(
        "/internal/heartbeat",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "login_state": "auth_required",
            "listening": False,
            "bot_delivery_state": "captcha_required",
            "bot_delivery_error": "captcha_required",
            "recorded_at": NOW.isoformat(),
        },
    )
    app_context.repository.enqueue_worker_command("pause_listening")

    response = app_context.client.get("/internal/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "state": "auth_required",
        "listening": False,
        "listening_desired": False,
        "bot_delivery_state": "captcha_required",
        "bot_delivery_error": "captcha_required",
        "last_heartbeat": "2026-08-04T20:00:00+08:00",
        "queue_counts": {
            "inbound_accepted": 1,
            "outbound_pending": 1,
            "worker_commands_pending": 1,
        },
    }


@pytest.mark.parametrize(
    "command",
    [
        "pause_listening",
        "resume_listening",
        "restart_browser",
        "start_auth",
        "finish_auth",
        "retract_test",
    ],
)
def test_allowed_worker_command_can_be_enqueued(client, headers, command):
    response = client.post(
        "/internal/worker-commands", headers=headers, json={"command": command}
    )

    assert response.status_code == 200
    assert response.json()["command"] == command
    assert response.json()["status"] == "pending"


def test_unknown_worker_command_is_rejected(client, headers):
    response = client.post(
        "/internal/worker-commands",
        headers=headers,
        json={"command": "delete_profile"},
    )

    assert response.status_code == 422


def test_worker_command_claim_and_fenced_completion(app_context, headers):
    command = app_context.client.post(
        "/internal/worker-commands",
        headers=headers,
        json={"command": "restart_browser"},
    ).json()
    first = app_context.client.post(
        "/internal/worker-commands/claim",
        headers=headers,
        json={"worker_id": "worker-a", "now": NOW.isoformat(), "lease_seconds": 30},
    ).json()
    second = app_context.client.post(
        "/internal/worker-commands/claim",
        headers=headers,
        json={
            "worker_id": "worker-b",
            "now": (NOW + timedelta(seconds=31)).isoformat(),
            "lease_seconds": 30,
        },
    ).json()

    stale = app_context.client.post(
        f"/internal/worker-commands/{command['id']}/complete",
        headers=headers,
        json={
            "worker_id": "worker-a",
            "lease_token": first["lease_token"],
            "status": "completed",
            "now": (NOW + timedelta(seconds=32)).isoformat(),
        },
    )
    with app_context.session_factory() as session:
        persisted_after_stale = session.scalar(
            select(WorkerCommandRecord).where(
                WorkerCommandRecord.id == UUID(command["id"])
            )
        )
        assert persisted_after_stale.status == "leased"
        assert persisted_after_stale.lease_worker_id == "worker-b"
        assert persisted_after_stale.lease_token == UUID(second["lease_token"])
        assert persisted_after_stale.completed_at is None

    fresh = app_context.client.post(
        f"/internal/worker-commands/{command['id']}/complete",
        headers=headers,
        json={
            "worker_id": "worker-b",
            "lease_token": second["lease_token"],
            "status": "completed",
            "now": (NOW + timedelta(seconds=32)).isoformat(),
        },
    )

    assert first["id"] == command["id"]
    assert second["id"] == command["id"]
    assert stale.json() == {"accepted": False}
    assert fresh.json() == {"accepted": True}
    assert (
        app_context.client.post(
            "/internal/worker-commands/claim",
            headers=headers,
            json={
                "worker_id": "worker-c",
                "now": (NOW + timedelta(seconds=63)).isoformat(),
                "lease_seconds": 30,
            },
        ).json()
        is None
    )


def test_worker_command_completion_requires_all_fencing_fields(client, headers):
    response = client.post(
        "/internal/worker-commands/00000000-0000-0000-0000-000000000000/complete",
        headers=headers,
        json={"status": "completed"},
    )

    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} == {
        "worker_id",
        "lease_token",
        "now",
    }


def test_random_event_settings_are_available_through_internal_api(client, headers):
    response = client.patch(
        "/internal/game/random-events/settings",
        headers=headers,
        json={
            "schedule_times": ["10:00", "14:00"],
            "signup_notice_template": "可选身份：{可选身份}",
            "signup_timeout_minutes": 15,
            "reminder_interval_minutes": 5,
            "signup_allowed_commands": ["/加入", "/退出", "/打卡"],
            "in_progress_allowed_commands": ["/退出", "/打卡"],
            "blocked_message": "当前有随机事件发生，监事不会处理。",
            "tipping_duration_seconds": 75,
        },
    )

    assert response.status_code == 200
    assert response.json()["schedule_times"] == ["10:00", "14:00"]
    assert response.json()["signup_allowed_commands"] == ["/加入", "/退出", "/打卡"]
    assert response.json()["in_progress_allowed_commands"] == ["/退出", "/打卡"]
    assert response.json()["tipping_duration_seconds"] == 75
    for duration in (9, 3601):
        invalid = client.patch(
            "/internal/game/random-events/settings",
            headers=headers,
            json={
                **response.json(),
                "tipping_duration_seconds": duration,
            },
        )
        assert invalid.status_code == 422


def test_random_event_tipping_is_visible_in_gameplay_and_event_details(
    app_context, headers
):
    from dzmm_bot.runtime.contracts import InboundMessage

    repository = app_context.repository
    now = NOW.astimezone(ZoneInfo("Asia/Shanghai"))
    repository.create_random_event_scene(
        "茶水间", "报名", ["正式开始。"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(
        [now.strftime("%H:%M")],
        "{可选身份}",
        15,
        5,
        tipping_duration_seconds=120,
    )
    repository.create_user("api-tip-target", "接口收款人", now, 0)
    repository.create_user("api-tip-donor", "接口打赏人", now, 10)
    schedule = repository.schedule_random_events(now)[0]
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("api-tip-target", "员工", now) == "started"
    assert repository.leave_random_event("api-tip-target", now) == "left_without_reward"
    repository.accept_inbound(
        InboundMessage(
            "api-tip-message",
            "api-tip-donor",
            "/打赏 接口收款人 3",
            now,
        )
    )
    assert repository.tip_random_event(
        "api-tip-donor", "接口收款人", 3, "api-tip-message", now
    ).status == "tipped"

    current = app_context.client.get("/internal/gameplay/current", headers=headers)
    details = app_context.client.get(
        f"/internal/game/random-events/today/{schedule.id}/details",
        headers=headers,
    )

    assert current.status_code == 200
    gameplay = current.json()["items"][0]
    assert gameplay["state"] == "tipping"
    assert gameplay["tipping_deadline"] == (
        now + timedelta(seconds=120)
    ).isoformat()
    assert gameplay["tip_total"] == 3
    assert [item["display_name"] for item in gameplay["participants"]] == [
        "接口收款人"
    ]
    assert details.json()["tips"] == [
        {
            "sender_display_name": "接口打赏人",
            "recipient_display_name": "接口收款人",
            "amount": 3,
            "created_at": now.isoformat(),
        }
    ]


def test_random_event_scene_is_created_through_internal_api(client, headers):
    response = client.post(
        "/internal/game/random-events/scenes",
        headers=headers,
        json={
            "name": "茶水间",
            "signup_text": "今天的公司茶水间随机事件来啦，快点加入吧。",
            "openings": ["咖啡机突然发出一声巨响。"],
            "reward": 4,
            "target_rounds": 10,
            "seats": [{"role": "员工", "capacity": 2}],
        },
    )

    assert response.status_code == 201
    assert response.json()["signup_text"] == "今天的公司茶水间随机事件来啦，快点加入吧。"
    assert response.json()["openings"] == ["咖啡机突然发出一声巨响。"]
    assert response.json()["seats"] == [{"role": "员工", "capacity": 2}]


def test_random_event_scene_duplicate_name_returns_clear_validation_error(client, headers):
    payload = {
        "name": "茶水间",
        "signup_text": "今天的公司茶水间随机事件来啦，快点加入吧。",
        "openings": ["咖啡机突然发出一声巨响。"],
        "reward": 4,
        "target_rounds": 10,
        "seats": [{"role": "员工", "capacity": 2}],
    }
    assert (
        client.post(
            "/internal/game/random-events/scenes", headers=headers, json=payload
        ).status_code
        == 201
    )

    response = client.post(
        "/internal/game/random-events/scenes", headers=headers, json=payload
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "场景名称已存在"


def test_random_event_scene_requires_a_formal_opening(client, headers):
    response = client.post(
        "/internal/game/random-events/scenes",
        headers=headers,
        json={
            "name": "茶水间",
            "signup_text": "今天的公司茶水间随机事件来啦，快点加入吧。",
            "openings": [],
            "reward": 4,
            "target_rounds": 10,
            "seats": [{"role": "员工", "capacity": 2}],
        },
    )

    assert response.status_code == 422


def test_random_event_scene_api_returns_named_events(client, headers):
    response = client.post(
        "/internal/game/random-events/scenes",
        headers=headers,
        json={
            "name": "茶水间",
            "signup_text": "报名",
            "events": [{"name": "咖啡事故", "opening_text": "开场"}],
            "reward": 1,
            "target_rounds": 1,
            "seats": [{"role": "员工", "capacity": 1}],
        },
    )

    assert response.status_code == 201
    assert response.json()["events"] == [{"name": "咖啡事故", "opening_text": "开场"}]


def test_today_random_event_can_be_added_and_removed_through_internal_api(
    client, headers
):
    scene = client.post(
        "/internal/game/random-events/scenes",
        headers=headers,
        json={
            "name": "茶水间",
            "signup_text": "报名",
            "events": [{"name": "咖啡事故", "opening_text": "开场"}],
            "reward": 1,
            "target_rounds": 1,
            "seats": [{"role": "员工", "capacity": 1}],
        },
    ).json()

    created = client.post(
        "/internal/game/random-events/today",
        headers=headers,
        json={
            "scene_id": scene["id"],
            "event_name": "咖啡事故",
            "scheduled_at": "2026-08-04T21:00:00+08:00",
        },
    )

    assert created.status_code == 200
    assert created.json()["scene_name"] == "茶水间"
    assert created.json()["event_name"] == "咖啡事故"
    assert client.delete(
        f"/internal/game/random-events/today/{created.json()['id']}", headers=headers
    ).json() == {"accepted": True}


def test_trigger_random_event_rejects_active_game_through_internal_api(
    app_context, headers
):
    repository = app_context.repository
    repository.create_user("u1", "小明", NOW, 0)
    repository.start_memory_assessment_single("u1", NOW)
    repository.create_random_event_scene(
        "茶水间",
        "报名",
        [{"name": "咖啡事故", "opening_text": "开场"}],
        1,
        1,
        [("员工", 1)],
    )
    repository.set_random_event_settings(["20:00"], "{可选身份}", 15, 5)
    schedule = repository.schedule_random_events(NOW)[0]

    response = app_context.client.post(
        f"/internal/game/random-events/today/{schedule.id}/trigger", headers=headers
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "当前有游戏进行中"}
    assert repository.list_today_random_event_schedules(NOW)[0].status == "pending"
