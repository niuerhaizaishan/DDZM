from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dzmm_bot.core.app import create_app
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.honors import HonorConflict, HonorGrantInput, midnight, week_of
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    AIRequestRecord, AuditEventRecord, Base, DailyCheckinRecord, DarkMarketListingRecord,
    EstrusChopRecord, GroupChatRecord, HonorAwardRecord, HonorPeriodRecord,
    HonorStateRecord, HonorWearRecord, OutboundRecord,
    PerformanceParticipantRecord, PerformanceReservationRecord, PerformanceTipRecord,
    PRIMARY_GROUP_CHAT_ID, RandomEventSubmissionRecord, UserRecord,
    RandomEventParticipantRecord, RandomEventRecord, RandomEventScheduleRecord, RandomEventTipRecord,
    GameParticipationRecord, KingGameRecord, KingGameRoundRecord,
    LiarDiceGameRecord, LiarDicePlayerRecord, LiarDiceRoundRecord,
    TexasHoldemGameRecord, TexasHoldemPlayerRecord,
    TruthTradeGameRecord, TruthTradePlayerRecord, TruthTradeQuestionRecord,
    MemoryGuildMatchRecord, MemoryGuildTeamRecord, MemoryGuildMemberRecord,
    MemoryGuildSeriesRecord, MemoryGuildRoundRecord, NeverHaveIEverGameRecord,
    NeverHaveIEverRoundRecord, NeverHaveIEverResponseRecord,
    NumberBombGameRecord, NumberBombRoundRecord, NumberBombRoundPlayerRecord,
    HideAndSeekGameRecord, MemoryAssessmentGameRecord, MemoryAssessmentParticipantRecord, MemoryAssessmentRoundRecord,
    UndercoverSessionRecord, UndercoverGameRecord, UndercoverGamePlayerRecord,
)
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage


INITIAL = midnight(date(2026, 9, 28))
WEEK = date(2026, 10, 5)
SETTLED = midnight(date(2026, 10, 12))


@pytest.fixture
def context():
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=group-main", INITIAL)
    for platform_id, name, gender in (("male-1", "糯糯", "male"),
                                      ("male-2", "米米", "male"),
                                      ("female-1", "小花", "female"),
                                      ("unknown-1", "未设置", "unknown")):
        user, _ = repository.create_user(platform_id, name, INITIAL - timedelta(days=90), 100)
        with factory.begin() as session:
            session.get(UserRecord, user.id).gender = gender
    repository.get_honor_config(INITIAL)
    yield repository, factory
    engine.dispose()


def configure(repository, now=INITIAL, **changes):
    config = repository.get_honor_config(now)
    payload = deepcopy(config["configuration"])
    payload.pop("activity_rules")
    payload.update(enabled=True, announce=False, expected_version=config["version"])
    payload.update(changes)
    return repository.update_honor_config(payload, "super-admin", now)


def chop(repository, factory, platform_id, count=1, group_id=PRIMARY_GROUP_CHAT_ID, now=None):
    user = repository.find_user(platform_id)
    with factory.begin() as session:
        session.add_all([EstrusChopRecord(group_chat_id=group_id, chopper_user_id=user.id,
            target_user_id=user.id, heat_gain=1, coins=0, climax_triggered=False,
            created_at=now or midnight(WEEK) + timedelta(hours=1)) for _ in range(count)])


def award(result, key):
    return next(item for item in result["awards"] if item["key"] == key)


def entry(report, key):
    return next(item for item in report["entries"] if item["key"] == key)


def message(repository, platform_id, content, now, group_id=PRIMARY_GROUP_CHAT_ID, source="group", content_type="text"):
    stored, _ = repository.accept_inbound(InboundMessage(str(uuid4()), platform_id, content, now,
                         source_type=source, content_type=content_type,
                         chatroom_id="group-main" if source == "group" else "dm"), group_id)
    return stored.id


def test_configuration_defaults_and_next_week_effect(context):
    repository, _ = context
    initial = repository.get_honor_config(INITIAL)
    assert not initial["current"]["enabled"]
    assert initial["configuration"]["announcement_time"] == "09:00"
    assert initial["first_week"] == "2026-09-28"
    assert len(initial["definitions"]) == 29
    assert sum(item["supported"] for item in initial["definitions"]) == 29
    updated = configure(repository)
    assert updated["effective_week"] == "2026-10-05"
    assert not updated["current"]["enabled"]
    assert repository.get_honor_config(midnight(WEEK))["current"]["enabled"]
    with pytest.raises(HonorConflict):
        payload = deepcopy(updated["configuration"])
        payload.pop("activity_rules")
        repository.update_honor_config({**payload, "expected_version": 0}, "other", INITIAL)


def candidate_score(report, key, user_id):
    return next((item["score"] for item in entry(report, key)["candidates"]
                 if item["user_id"] == str(user_id)), 0)


def test_phase_two_game_counts_and_king_round_metrics(context):
    repository, factory = context
    configure(repository)
    host = repository.find_user("male-1").id
    other = repository.find_user("male-2").id
    outsider = repository.find_user("female-1").id
    start = midnight(WEEK)
    group_id = uuid4()
    with factory.begin() as session:
        session.add(GroupChatRecord(id=group_id, name="未选群", chat_url="https://example.com/other",
                                   chatroom_id="other", created_at=INITIAL, updated_at=INITIAL,
                                   listening_enabled=True, games_enabled=True,
                                   random_events_enabled=False, announcements_enabled=False))
        for state, group, finished, rounds in (
            ("completed", PRIMARY_GROUP_CHAT_ID, start + timedelta(days=1), 2),
            ("forced_ended", PRIMARY_GROUP_CHAT_ID, start + timedelta(days=2), 1),
            ("forced_ended", PRIMARY_GROUP_CHAT_ID, start + timedelta(days=3), 0),
            ("completed", group_id, start + timedelta(days=1), 1),
            ("completed", PRIMARY_GROUP_CHAT_ID, SETTLED, 1),
        ):
            game = KingGameRecord(host_user_id=host, state=state, group_chat_id=group,
                                  started_at=start, finished_at=finished)
            session.add(game)
            session.flush()
            for sequence in range(1, rounds + 1):
                session.add(KingGameRoundRecord(game_id=game.id, sequence=sequence,
                    king_user_id=host, number_map={str(host): 1, str(other): 2},
                    revealed_numbers=[1, 2, 2], state="revealed", started_at=start,
                    revealed_at=finished))
            session.add(KingGameRoundRecord(game_id=game.id, sequence=rounds + 1,
                king_user_id=outsider, number_map={str(outsider): 1}, state="timed_out", started_at=start))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", host) == 2
    assert candidate_score(report, "game_king", other) == 2
    assert candidate_score(report, "game_king", outsider) == 0
    assert candidate_score(report, "boomerang", host) == 3
    assert candidate_score(report, "punished", other) == 3
    assert candidate_score(report, "lucky", host) == 3
    assert candidate_score(report, "lucky", outsider) == 0
    assert repository.preview_honors(WEEK, SETTLED)["preview_digest"] == report["preview_digest"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(GameParticipationRecord)) == 4


def test_chop_honor_metric_is_shared_across_groups(context):
    repository, factory = context
    configure(repository)
    second_group = repository.create_group_chat(
        "二群",
        "https://www.aikda.com/chat?c=group-second",
        True,
        True,
        True,
        True,
        INITIAL,
    )
    chop(repository, factory, "male-1", group_id=PRIMARY_GROUP_CHAT_ID, now=midnight(WEEK))
    chop(repository, factory, "male-1", group_id=second_group.id, now=midnight(WEEK) + timedelta(hours=1))

    report = repository.preview_honors(WEEK, SETTLED)
    user_id = repository.find_user("male-1").id
    assert candidate_score(report, "charm_m", user_id) == 2


@pytest.mark.parametrize("revealed", [False, True])
def test_phase_two_admin_force_end_king_game_records_only_revealed_games(context, revealed):
    repository, factory = context
    start = midnight(WEEK)
    repository.start_king_game("male-1", start)
    repository.join_king_game("male-2", start)
    repository.join_king_game("female-1", start)
    result = repository.begin_king_game("male-1", start)
    if revealed:
        repository.reveal_king_game_numbers(result.king_platform_id, "1", start)
    assert repository.force_end_gameplay("king_game", result.game_id, start)
    assert not repository.force_end_gameplay("king_game", result.game_id, start)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(GameParticipationRecord)) == (3 if revealed else 0)


@pytest.mark.parametrize("mode", ["standard", "points_tournament"])
def test_number_bomb_round_honors_add_to_king_scores_and_exclude_invalid_results(context, mode):
    repository, factory = context
    configure(repository)
    host, other, tied, absent = [repository.find_user(platform_id).id
                               for platform_id in ("male-1", "male-2", "female-1", "unknown-1")]
    start = midnight(WEEK)
    outside_group = uuid4()
    with factory.begin() as session:
        session.add(GroupChatRecord(id=outside_group, name="未选数字炸弹群", chatroom_id="bomb-other",
            created_at=INITIAL, updated_at=INITIAL, listening_enabled=True, games_enabled=True,
            random_events_enabled=False, announcements_enabled=False))
        king = KingGameRecord(host_user_id=host, state="revealed", started_at=start)
        session.add(king)
        session.flush()
        session.add(KingGameRoundRecord(game_id=king.id, sequence=1, king_user_id=host,
            number_map={str(host): 1, str(other): 2}, revealed_numbers=[2], state="revealed",
            started_at=start, revealed_at=start))
        for group_id in (PRIMARY_GROUP_CHAT_ID, outside_group):
            game = NumberBombGameRecord(group_chat_id=group_id, state="waiting_continue", mode=mode,
                maximum_rounds=12 if mode == "points_tournament" else 0,
                target_player_count=8, last_activity_at=start, started_at=start)
            session.add(game)
            session.flush()
            cases = [
                ("settled", start, 10, None, None),
                ("settled", SETTLED - timedelta(microseconds=1), 10, None, "reported"),
                ("invalid", start, 10, None, None),
                ("collecting", start, 10, None, None),
                ("voided", start, 10, None, None),
                ("settled", None, 10, None, None),
                ("settled", start - timedelta(microseconds=1), 10, None, None),
                ("settled", SETTLED, 10, None, None),
                ("settled", start, None, None, "skipped"),
                ("settled", start, None, None, "retired"),
                ("settled", start, 10, start, None),
                ("settled", start, 10, None, "skipped"),
                ("settled", start, 10, None, "retired"),
            ]
            for sequence, (state, finished_at, submitted, skipped_at, reason) in enumerate(cases, 1):
                round_record = NumberBombRoundRecord(game_id=game.id, round_number=sequence,
                    attempt_number=1, punishment_type="truth", state=state, player_count=4,
                    created_at=start, finished_at=finished_at)
                session.add(round_record)
                session.flush()
                for seat, (user_id, result) in enumerate(((host, "winner"), (other, "punished"),
                                                        (tied, "winner")), 1):
                    session.add(NumberBombRoundPlayerRecord(round_id=round_record.id, user_id=user_id,
                        display_order=seat, result=result, submitted_number=submitted,
                        skipped_at=skipped_at, result_reason=reason))
                session.add(NumberBombRoundPlayerRecord(round_id=round_record.id, user_id=absent,
                    display_order=4, result="punished", submitted_number=None, result_reason="retired"))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "lucky", host) == 3
    assert candidate_score(report, "lucky", tied) == 2
    assert candidate_score(report, "punished", other) == 3
    assert candidate_score(report, "punished", absent) == 0
    assert candidate_score(report, "game_king", host) == 0
    assert candidate_score(report, "boomerang", host) == 0
    assert repository.preview_honors(WEEK, SETTLED)["preview_digest"] == report["preview_digest"]
    settled = repository.settle_honors(WEEK, "admin", SETTLED, report["preview_digest"])
    assert award(settled, "lucky")["user_id"] == str(host)
    assert award(settled, "lucky")["score"] == 3
    assert award(settled, "punished")["user_id"] == str(other)
    assert award(settled, "punished")["score"] == 3


def test_phase_two_texas_uses_weekly_net_and_only_final_settlement(context):
    repository, factory = context
    configure(repository)
    host = repository.find_user("male-1").id
    other = repository.find_user("male-2").id
    outsider = repository.find_user("female-1").id
    start = midnight(WEEK)
    with factory.begin() as session:
        for offset, payout, state, complete, finished in (
            (1, 160, "settled", True, start),
            (2, 50, "settled", True, start + timedelta(days=6)),
            (3, 1000, "cancelled", True, start),
            (4, 1000, "settled", False, start),
            (5, 1000, "settled", True, SETTLED),
        ):
            game = TexasHoldemGameRecord(creator_user_id=host, state=state, buy_in=100,
                created_at=start - timedelta(hours=1), signup_deadline=start,
                started_at=start, finished_at=finished, settlement_complete=complete)
            session.add(game)
            session.flush()
            session.add_all([
                TexasHoldemPlayerRecord(game_id=game.id, user_id=host, seat_number=1,
                    original_buy_in=100, stack=payout, state="finished", joined_at=start),
                TexasHoldemPlayerRecord(game_id=game.id, user_id=other, seat_number=2,
                    original_buy_in=100, stack=200 - payout, state="folded", joined_at=start),
                TexasHoldemPlayerRecord(game_id=game.id, user_id=outsider,
                    original_buy_in=100, stack=1000, state="withdrawn", joined_at=start),
            ])
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "poker_profit", host) == 10
    assert candidate_score(report, "poker_loss", host) == 0
    assert candidate_score(report, "poker_loss", other) == 10
    assert candidate_score(report, "poker_profit", other) == 0
    assert candidate_score(report, "poker_count", host) == 2
    assert candidate_score(report, "poker_count", other) == 2
    assert candidate_score(report, "poker_count", outsider) == 0
    assert candidate_score(report, "game_king", host) == 2


def test_phase_two_bot_interactions_exclude_failure_blank_direct_and_other_week(context):
    repository, factory = context
    configure(repository)
    user_id = repository.find_user("male-1").id
    for source, status, text, completed in (
        ("group", "completed", "回复内容", midnight(WEEK)),
        ("group", "failed", "失败", midnight(WEEK)),
        ("group", "pending", "尚未完成", None),
        ("group", "completed", " \n\t", midnight(WEEK)),
        ("direct", "completed", "私聊", midnight(WEEK)),
        ("group", "completed", "下周", SETTLED),
    ):
        inbound_id = message(repository, "male-1", "@总监事 你好", INITIAL, source=source)
        with factory.begin() as session:
            session.add(AIRequestRecord(inbound_message_id=inbound_id, user_id=user_id, status=status,
                result_text=text, completed_at=completed, created_at=INITIAL, attempt_count=3))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "bot_friend", user_id) == 1
    result = repository.settle_honors(WEEK, "admin", SETTLED, report["preview_digest"])
    assert award(result, "bot_friend")["user_id"] == str(user_id)


@pytest.mark.parametrize("legacy", [False, True])
def test_phase_two_liar_dice_multiple_rounds_count_one_game(context, legacy):
    repository, factory = context
    configure(repository)
    host = repository.find_user("male-1").id
    other = repository.find_user("male-2").id
    withdrawn = repository.find_user("female-1").id
    start = midnight(WEEK)
    with factory.begin() as session:
        for state, resolved in (("completed", True), ("forced_ended", True),
                                ("forced_ended", False), ("cancelled", True)):
            game = LiarDiceGameRecord(host_user_id=host, state=state,
                                     started_at=start, finished_at=start + timedelta(days=1))
            session.add(game)
            session.flush()
            for seat, user_id in enumerate((host, other, withdrawn), 1):
                session.add(LiarDicePlayerRecord(game_id=game.id, user_id=user_id,
                    seat_number=seat if seat < 3 else None, state="active" if seat < 3 else "left",
                    joined_at=start - timedelta(minutes=5), left_at=start if seat == 3 else None))
            for sequence in (1, 2):
                session.add(LiarDiceRoundRecord(game_id=game.id, sequence=sequence,
                    wild_face=1, state="resolved" if resolved else "voided", started_at=start,
                    resolved_at=start + timedelta(hours=1) if resolved else None,
                    dice_snapshot={"旧昵称甲": [1], "旧昵称乙": [2]} if legacy
                    else {str(host): [1], str(other): [2]}))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", host) == 2
    assert candidate_score(report, "game_king", other) == 2
    assert candidate_score(report, "game_king", withdrawn) == 0


def test_phase_two_legacy_truth_trade_partial_round_not_counted(context):
    repository, factory = context
    configure(repository)
    host = repository.find_user("male-1").id
    other = repository.find_user("male-2").id
    start = midnight(WEEK)
    with factory.begin() as session:
        for complete in (False, True):
            game = TruthTradeGameRecord(host_user_id=host, state="finished", settled_rounds=1,
                round_number=1, started_at=start, finished_at=start + timedelta(hours=2))
            session.add(game)
            session.flush()
            players = [TruthTradePlayerRecord(game_id=game.id, user_id=user_id, position=position,
                state="active", joined_at=start - timedelta(minutes=1))
                for position, user_id in enumerate((host, other), 1)]
            session.add_all(players)
            session.flush()
            for player in players if complete else players[:1]:
                session.add(TruthTradeQuestionRecord(game_id=game.id, asker_player_id=player.id,
                    round_number=1, position=player.position, state="skipped", asked_at=start,
                    collected_at=start + timedelta(hours=1)))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", host) == 1
    assert candidate_score(report, "game_king", other) == 1


def test_phase_two_completed_rounds_include_real_players_only(context):
    repository, factory = context
    configure(repository)
    host = repository.find_user("male-1").id
    other = repository.find_user("male-2").id
    start = midnight(WEEK)
    with factory.begin() as session:
        for completed in (False, True):
            never = NeverHaveIEverGameRecord(host_user_id=host, state="forced_ended", started_at=start,
                                            finished_at=start + timedelta(hours=1))
            number = NumberBombGameRecord(state="ended", target_player_count=3, last_activity_at=start,
                                          started_at=start, finished_at=start + timedelta(hours=1))
            session.add_all([never, number])
            session.flush()
            for sequence in (1, 2):
                never_round = NeverHaveIEverRoundRecord(game_id=never.id, sequence=sequence,
                    speaker_user_id=host, state="settled" if completed else "awaiting_responses",
                    settled_at=start + timedelta(minutes=30) if completed else None)
                number_round = NumberBombRoundRecord(game_id=number.id, round_number=sequence,
                    attempt_number=1, punishment_type="truth", state="settled" if completed else "invalid",
                    player_count=3, created_at=start, finished_at=start + timedelta(minutes=30))
                session.add_all([never_round, number_round])
                session.flush()
                session.add(NeverHaveIEverResponseRecord(round_id=never_round.id, user_id=other,
                    choice="keep", submitted_at=start))
                session.add_all([
                    NumberBombRoundPlayerRecord(round_id=number_round.id, user_id=host,
                                                display_order=1, submitted_number=10),
                    NumberBombRoundPlayerRecord(round_id=number_round.id, user_id=other,
                                                display_order=2, submitted_number=None),
                ])
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", host) == 2
    assert candidate_score(report, "game_king", other) == 1


def test_phase_two_memory_guild_counts_finished_lineups_excludes_bench(context):
    repository, factory = context
    configure(repository)
    users = [repository.find_user(platform_id).id for platform_id in ("male-1", "male-2", "female-1")]
    start = midnight(WEEK)
    with factory.begin() as session:
        for completed_round in (False, True):
            match = MemoryGuildMatchRecord(group_chat_id=PRIMARY_GROUP_CHAT_ID, host_user_id=users[0],
                state="forced_ended", planned_series_count=1, finished_at=start + timedelta(hours=1))
            session.add(match)
            session.flush()
            teams = [MemoryGuildTeamRecord(match_id=match.id, slot=slot) for slot in (1, 2)]
            session.add_all(teams)
            session.flush()
            members = [MemoryGuildMemberRecord(match_id=match.id, team_id=teams[index % 2].id,
                user_id=user_id, display_name_snapshot=str(index), roster_order=index + 1)
                for index, user_id in enumerate(users)]
            session.add_all(members)
            session.flush()
            series = MemoryGuildSeriesRecord(match_id=match.id, sequence=1, state="playing",
                win_target=1, maximum_decisive_rounds=1, team1_member_id=members[0].id,
                team2_member_id=members[1].id)
            session.add(series)
            session.flush()
            for sequence in (1, 2):
                session.add(MemoryGuildRoundRecord(match_id=match.id, series_id=series.id,
                    sequence=sequence, answer="123", display_seconds=3,
                    state="drawn" if completed_round else "answering"))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", users[0]) == 1
    assert candidate_score(report, "game_king", users[1]) == 1
    assert candidate_score(report, "game_king", users[2]) == 0


def test_phase_two_other_sources_handle_real_terminal_states(context):
    repository, factory = context
    configure(repository)
    host = repository.find_user("male-1").id
    other = repository.find_user("male-2").id
    start = midnight(WEEK)
    with factory.begin() as session:
        for state, selected in (("won", 1), ("found", 1), ("cancelled", None)):
            session.add(HideAndSeekGameRecord(user_id=host, play_date=WEEK, state=state,
                candidates=["办公室"], selected_number=selected, entry_fee=1, win_reward=2,
                choice_deadline=start, finished_at=start))
        for state, participant_states in (("settled", ("winner", "surrendered")),
                                          ("cancelled", ("cancelled", "cancelled")),
                                          ("collected", ("disqualified", "disqualified"))):
            memory = MemoryAssessmentGameRecord(mode="duel", state=state, play_date=WEEK, finished_at=start)
            session.add(memory)
            session.flush()
            for user_id, participant_state in zip((host, other), participant_states):
                session.add(MemoryAssessmentParticipantRecord(game_id=memory.id, user_id=user_id,
                                                              state=participant_state))
        undercover_session = UndercoverSessionRecord(state="closed", target_player_count=3)
        session.add(undercover_session)
        session.flush()
        for sequence, state, eliminated in ((1, "settled", True), (2, "ended", True), (3, "ended", False)):
            game = UndercoverGameRecord(session_id=undercover_session.id, round_number=sequence,
                state=state, civilian_word="苹果", undercover_word="梨", vote_seconds_snapshot=60,
                whiteboard_win_remaining_snapshot=2, finished_at=start)
            session.add(game)
            session.flush()
            for seat, user_id in enumerate((host, other), 1):
                session.add(UndercoverGamePlayerRecord(game_id=game.id, user_id=user_id,
                    seat_number=seat, role="civilian", card_delivery_state="delivered" if seat == 1 else "failed",
                    state="eliminated" if eliminated and seat == 1 else "alive"))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", host) == 6
    assert candidate_score(report, "game_king", other) == 2


@pytest.mark.parametrize("completed_round", [False, True])
def test_phase_two_forced_memory_end_requires_completed_round(context, completed_round):
    repository, factory = context
    configure(repository)
    user_id = repository.find_user("male-1").id
    start = midnight(WEEK)
    with factory.begin() as session:
        game = MemoryAssessmentGameRecord(mode="single", state="cancelled", play_date=WEEK, finished_at=start)
        session.add(game)
        session.flush()
        session.add(MemoryAssessmentParticipantRecord(game_id=game.id, user_id=user_id, state="cancelled"))
        session.add(MemoryAssessmentRoundRecord(game_id=game.id, sequence=1, answer="123",
            display_seconds=3, state="answered" if completed_round else "awaiting_answer"))
    report = repository.preview_honors(WEEK, SETTLED)
    assert candidate_score(report, "game_king", user_id) == (1 if completed_round else 0)


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "brackets", "zero", "level", "groups"])
def test_configuration_rejects_invalid_rules_without_side_effects(context, invalid):
    repository, _ = context
    rules = deepcopy(repository.get_honor_config(INITIAL)["configuration"]["rules"])
    changes = {"rules": rules}
    if invalid == "missing":
        rules[-1]["key"] = "unknown_title"
    elif invalid == "duplicate":
        rules[1]["name"] = rules[0]["name"]
    elif invalid == "brackets":
        rules[0]["name"] = "【坏名称】"
    elif invalid == "zero":
        rules[0]["minimum"] = 0
    elif invalid == "level":
        rules[1]["minimum"] = 11
    else:
        changes["group_ids"] = [str(uuid4())]
    with pytest.raises(ValueError):
        configure(repository, **changes)
    assert repository.get_honor_config(INITIAL)["version"] == 0


def test_settlement_is_idempotent_and_snapshot_is_immutable(context):
    repository, factory = context
    configure(repository, announce=True)
    chop(repository, factory, "male-1", 3)
    preview = repository.preview_honors(WEEK, SETTLED)
    balances = [user.balance for user in repository.list_users()]
    result = repository.settle_honors(WEEK, "admin", SETTLED, preview["preview_digest"])
    assert award(result, "charm_m")["winner_name"] == "糯糯"
    assert award(result, "charm_m")["score"] == 3
    assert award(result, "game_king")["user_id"] is None
    chop(repository, factory, "male-2", 10)
    repository.rename_user("male-1", "改名以后")
    assert repository.settle_honors(WEEK, "retry", SETTLED)["id"] == result["id"]
    saved = repository.preview_honors(WEEK, SETTLED)
    assert saved["preview_digest"] == preview["preview_digest"]
    assert entry(saved, "charm_m")["candidates"][0]["name"] == "糯糯"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HonorPeriodRecord)) == 1
        assert session.scalar(select(func.count()).select_from(HonorAwardRecord)) == 29
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.event_type == "honor_settlement")) == 1
    assert [user.balance for user in repository.list_users()] == balances


def test_changed_preview_and_unfinished_week_cannot_settle(context):
    repository, factory = context
    configure(repository)
    preview = repository.preview_honors(WEEK, SETTLED)
    chop(repository, factory, "male-1")
    with pytest.raises(HonorConflict):
        repository.settle_honors(WEEK, "admin", SETTLED, preview["preview_digest"])
    with pytest.raises(ValueError, match="尚未结束"):
        repository.settle_honors(WEEK, "admin", midnight(WEEK))
    assert repository.honor_periods()["total"] == 0
    assert not repository.preview_honors(WEEK, midnight(WEEK))["can_settle"]


def test_permanent_honor_chat_commands_outlast_weekly_awards(context):
    repository, factory = context
    configure(repository)
    chop(repository, factory, "male-1")
    repository.settle_honors(WEEK, "admin", SETTLED)
    with factory() as session:
        number = session.scalar(select(UserRecord.employee_number).where(UserRecord.platform_id == "male-1"))
    award = repository.grant_permanent_honor(HonorGrantInput(
        employee_number=number, name="年度热心同事", reason="协助新人入职",
    ), "admin", SETTLED)
    handler = GroupCommandHandler(repository)
    later = SETTLED + timedelta(days=365)

    def command(text, now=SETTLED):
        return handler.handle(InboundMessage(str(uuid4()), "male-1", text, now,
                                             source_type="direct", chatroom_id="dm"))

    titles = command("/我的称号")
    assert "1. 公司最靓的仔｜历史获得 1 次｜有效至" in titles
    assert "2. 年度热心同事｜历史获得 1 次｜永久" in titles
    assert "已佩戴" in command("/佩戴称号 2")
    repository.run_honor_jobs(later)
    assert command("/我", later).startswith("糯糯【荣誉称号：年度热心同事】")
    assert "年度热心同事｜永久" in command("/荣誉历史", later)
    repository.revoke_permanent_honor(UUID(award["id"]), "本人申请", "admin", later)
    assert "年度热心同事" not in command("/我", later)
    assert "年度热心同事｜已撤回" in command("/荣誉历史", later)


@pytest.mark.parametrize("wear_command", ["/佩戴称号", "/装备称号", "/编辑称号"])
def test_name_suffix_wear_cancel_expiry_and_direct_commands(context, wear_command):
    repository, factory = context
    configure(repository)
    chop(repository, factory, "male-1")
    repository.settle_honors(WEEK, "admin", SETTLED)
    handler = GroupCommandHandler(repository)

    def command(text, now=SETTLED):
        text = text.replace("/佩戴称号", wear_command, 1)
        return handler.handle(InboundMessage(str(uuid4()), "male-1", text, now,
                                             source_type="direct", chatroom_id="dm"))

    assert command("/我").splitlines()[0] == "糯糯"
    honors_text = command("/我的称号")
    assert "公司最靓的仔" in honors_text
    assert "有效至 2026-10-19 00:00" in honors_text
    assert "历史累计获得荣誉 1 次。" in honors_text
    assert "发送 /装备称号 序号 切换" in honors_text
    assert "已佩戴" in command("/佩戴称号 1")
    assert command("/我").splitlines()[0] == "糯糯【荣誉称号：公司最靓的仔】"
    assert command("/me").splitlines()[0] == "糯糯【荣誉称号：公司最靓的仔】"
    repository.edit_own_profile("male-1", "我的个人档案")
    assert command("/我的档案").startswith("糯糯【荣誉称号：公司最靓的仔】\n")
    assert "序号无效" in command("/佩戴称号 9")
    assert "用法" in command("/佩戴称号 -1")
    service = CoreService(repository, handler)
    service.receive_inbound(InboundMessage("wear-direct", "male-1", f"{wear_command} 1", SETTLED,
                                           source_type="direct", chatroom_id="dm"))
    repository.upsert_direct_chats([("male-1", "dm")], SETTLED)
    with factory() as session:
        assert "已佩戴" in session.scalar(select(OutboundRecord).where(OutboundRecord.delivery_kind == "direct")).text
    assert "已取消" in command("/佩戴称号 0")
    assert command("/我").splitlines()[0] == "糯糯"
    command("/佩戴称号 1")
    expired = SETTLED + timedelta(days=7)
    assert command("/我", expired).splitlines()[0] == "糯糯"
    assert repository.my_honors("male-1", expired)["items"] == []
    assert repository.my_honors("male-1", expired)["history_counts"] == {"charm_m": 1}
    repository.run_honor_jobs(expired)
    repository.run_honor_jobs(expired)
    with factory() as session:
        assert session.get(HonorWearRecord, repository.find_user("male-1").id) is None
        notices = session.scalars(select(OutboundRecord).where(OutboundRecord.text.contains("已失效"))).all()
        assert len(notices) == 1
    repository.set_command_enabled("/佩戴称号", False)
    assert command("/佩戴称号 0") is None


def test_correction_requires_candidate_reason_revision_and_clears_wear(context):
    repository, factory = context
    configure(repository)
    chop(repository, factory, "male-1", 2)
    chop(repository, factory, "male-2", 1)
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    won = award(result, "charm_m")
    repository.wear_honor("male-1", 1, SETTLED)
    recipient = repository.find_user("male-2")
    with pytest.raises(ValueError, match="原因"):
        repository.correct_honor(UUID(won["id"]), recipient.id, " ", 1, "admin", SETTLED)
    with pytest.raises(ValueError, match="候选人"):
        repository.correct_honor(UUID(won["id"]), repository.find_user("female-1").id,
                                 "不能越过资格", 1, "admin", SETTLED)
    corrected = repository.correct_honor(UUID(won["id"]), recipient.id, "管理员核对", 1, "admin", SETTLED)
    assert corrected["revision"] == 2
    assert award(corrected, "charm_m")["winner_name"] == "米米"
    assert repository.get_equipped_honor("male-1", SETTLED) is None
    assert repository.my_honors("male-1", SETTLED)["history_counts"] == {}
    with pytest.raises(HonorConflict):
        repository.correct_honor(UUID(won["id"]), None, "旧页面", 1, "admin", SETTLED)
    with factory() as session:
        audit = session.scalar(select(AuditEventRecord).where(AuditEventRecord.event_type == "honor_correction"))
        assert audit.payload["before"]["winner_name"] == "糯糯"
        assert audit.payload["after"]["winner_name"] == "米米"
        assert audit.payload["reason"] == "管理员核对"


def test_settlement_rollback_and_retry(context, monkeypatch):
    repository, factory = context
    configure(repository, announce=True)
    chop(repository, factory, "male-1")
    original = repository.enqueue_system_outbound

    def fail(*args, **kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(repository, "enqueue_system_outbound", fail)
    with pytest.raises(RuntimeError):
        repository.settle_honors(WEEK, "admin", SETTLED)
    assert repository.honor_periods()["total"] == 0
    monkeypatch.setattr(repository, "enqueue_system_outbound", original)
    assert repository.settle_honors(WEEK, "admin", SETTLED)["announced_at"] is not None


def test_late_backfill_keeps_original_expiry_and_resumes_cursor(context):
    repository, factory = context
    configure(repository, announce=True)
    chop(repository, factory, "male-1")
    late = SETTLED + timedelta(weeks=8)
    result = repository.settle_honors(WEEK, "late", late)
    assert award(result, "charm_m")["expires_at"].startswith("2026-10-19T00:00:00")
    assert repository.my_honors("male-1", late)["items"] == []
    assert result["announced_at"] is None
    repository.run_honor_jobs(late)
    with factory() as session:
        assert session.get(HonorStateRecord, 1).next_week == date(2026, 10, 26)
    for _ in range(3):
        repository.run_honor_jobs(late)
    with factory() as session:
        assert session.get(HonorStateRecord, 1).next_week == week_of(late)
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1


def test_bulk_backfill_settles_only_missing_ended_periods_and_is_idempotent(context):
    repository, factory = context
    configure(repository, announce=False)
    repository.settle_honors(WEEK, "manual", SETTLED)
    now = midnight(date(2026, 10, 26))

    result = repository.backfill_missing_honor_periods("admin", now)

    assert result["settled_weeks"] == ["2026-09-28", "2026-10-12", "2026-10-19"]
    assert result["count"] == 3
    assert result["next_week"] == "2026-10-26"
    assert repository.honor_periods()["total"] == 4
    assert repository.backfill_missing_honor_periods("admin", now)["count"] == 0
    with factory() as session:
        assert session.get(HonorStateRecord, 1).next_week == date(2026, 10, 26)


def test_seven_day_activity_streak_gender_and_scope(context):
    repository, factory = context
    configure(repository)
    config = repository.get_honor_config(midnight(WEEK))["current"]
    lv10 = max(threshold for level, threshold in config["activity_rules"] if level == 10)
    outsider = uuid4()
    with factory.begin() as session:
        session.add(GroupChatRecord(id=outsider, name="其他群", chatroom_id="other",
            listening_enabled=True, games_enabled=True, random_events_enabled=True,
            announcements_enabled=True, created_at=INITIAL, updated_at=INITIAL))
        for platform_id, days in (("male-1", 30), ("male-2", 7), ("unknown-1", 7)):
            user = repository.find_user(platform_id)
            for offset in range(days):
                day = WEEK + timedelta(days=6-offset)
                session.add(DailyCheckinRecord(user_id=user.id, checkin_date=day, checked_in_at=midnight(day)))
    for offset in range(7):
        now = midnight(WEEK) + timedelta(days=offset, hours=2)
        message(repository, "male-1", "水" * lv10, now)
        message(repository, "male-2", "水" * lv10, now, outsider)
        message(repository, "male-2", "/无关 " + "水" * lv10, now)
        message(repository, "male-2", "水" * lv10, now, source="direct")
        message(repository, "male-2", "水" * lv10, now, content_type="system")
    chop(repository, factory, "unknown-1", 99)
    preview = repository.preview_honors(WEEK, SETTLED)
    assert entry(preview, "chatter")["candidates"][0]["score"] == lv10 * 7
    assert entry(preview, "chatter")["candidates"][0]["eligible"]
    assert not next(item for item in entry(preview, "slacker")["candidates"] if item["name"] == "糯糯")["eligible"]
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    assert {item["winner_name"] for item in result["awards"] if item["key"] == "checkin_king"} == {"糯糯", "米米", "未设置"}
    assert award(result, "checkin_god")["winner_name"] == "糯糯"
    assert award(result, "chatter")["winner_name"] == "糯糯"
    assert award(result, "slacker")["winner_name"] in {"米米", "未设置"}
    assert award(result, "charm_m")["user_id"] is None
    assert award(result, "charm_f")["user_id"] is None


def performance(factory, owner, now, state="completed"):
    with factory.begin() as session:
        record = PerformanceReservationRecord(owner_user_id=owner.id, group_chat_id=PRIMARY_GROUP_CHAT_ID,
            title="公演", introduction="测试", scheduled_at=now, event_date=now.date(),
            state=state, submitted_at=now, ended_at=now)
        session.add(record)
        session.flush()
        session.add(PerformanceParticipantRecord(reservation_id=record.id, user_id=owner.id, display_order=1))
        return record.id


@pytest.mark.parametrize("first_enabled", [True, False])
def test_tied_tip_ranking_separates_first_second_even_when_first_disabled(context, monkeypatch, first_enabled):
    repository, factory = context
    rules = repository.get_honor_config(INITIAL)["configuration"]["rules"]
    next(rule for rule in rules if rule["key"] == "tip_first_m")["enabled"] = first_enabled
    configure(repository, rules=rules)
    now = midnight(WEEK) + timedelta(hours=1)
    owner = repository.find_user("female-1")
    reservation_id = performance(factory, owner, now)
    for sender in ("male-1", "male-2"):
        inbound = message(repository, sender, "/打赏", now)
        with factory.begin() as session:
            session.add(PerformanceTipRecord(reservation_id=reservation_id,
                sender_user_id=repository.find_user(sender).id, recipient_user_id=owner.id,
                amount=100, inbound_message_id=inbound, created_at=now))
    monkeypatch.setattr("dzmm_bot.core.honors.choice", lambda candidates: candidates[0])
    preview = repository.preview_honors(WEEK, SETTLED)
    ranking = preview["tip_rankings"]["male"]
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    first, second = award(result, "tip_first_m"), award(result, "tip_second_m")
    assert first["user_id"] == (ranking[0]["user_id"] if first_enabled else None)
    assert second["user_id"] == ranking[1]["user_id"]
    assert award(result, "actor_f")["score"] == 200
    assert award(result, "performer_f")["score"] == 1
    if first_enabled:
        with pytest.raises(ValueError, match="同一人"):
            repository.correct_honor(UUID(second["id"]), UUID(first["user_id"]), "纠错", 1, "admin", SETTLED)
    assert repository.settle_honors(WEEK, "retry", SETTLED)["awards"] == result["awards"]


def test_submission_and_actual_sold_market_use_final_time_and_net_income(context):
    repository, factory = context
    configure(repository)
    now = midnight(WEEK) + timedelta(hours=1)
    seller = repository.find_user("female-1")
    buyer = repository.find_user("male-1")
    with factory.begin() as session:
        for number, status, reviewed in ((1, "approved", now), (2, "pending", None),
                                         (3, "approved", SETTLED)):
            session.add(RandomEventSubmissionRecord(number=number, user_id=seller.id, status=status,
                reviewed_at=reviewed, last_activity_at=now, created_at=INITIAL))
        for number, state, finished in ((1, "sold", now), (2, "active", None),
                                        (3, "complained", now), (4, "sold", SETTLED)):
            session.add(DarkMarketListingRecord(public_number=number, seller_user_id=seller.id,
                announcement_group_id=PRIMARY_GROUP_CHAT_ID, buyer_user_id=buyer.id,
                name="商品", purpose="测试", details="测试", gender="female", starting_price=1,
                duration_hours_snapshot=24, fee_percent_snapshot=10, state=state,
                ends_at=now, created_at=INITIAL, finished_at=finished, final_amount=100, fee_amount=10))
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    assert award(result, "submission")["score"] == 1
    assert award(result, "seller_f")["score"] == 1
    assert award(result, "buyer_m")["score"] == 100
    assert award(result, "market_star")["score"] == 90


def test_core_api_auth_validation_conflicts_and_employee_display(context):
    repository, factory = context
    configure(repository)
    chop(repository, factory, "male-1")
    client = TestClient(create_app(repository, "secret", clock=lambda: SETTLED))
    root = "/internal/game/honors"
    headers = {"X-Core-Token": "secret"}
    assert client.get(root + "/config").status_code == 401
    assert client.get(root + "/preview?week_start=2026-10-06", headers=headers).status_code == 422
    assert client.get(root + "/history?user_id=invalid", headers=headers).status_code == 422
    preview = client.get(root + "/preview?week_start=2026-10-05", headers=headers).json()
    payload = {"week_start": "2026-10-05", "preview_digest": "0" * 64, "actor": "admin"}
    assert client.post(root + "/settle", headers=headers, json=payload).status_code == 409
    payload["preview_digest"] = preview["preview_digest"]
    assert client.post(root + "/settle", headers=headers, json=payload).status_code == 200
    repository.wear_honor("male-1", 1, SETTLED)
    users = client.get("/internal/game/users", headers=headers).json()["items"]
    user = next(item for item in users if item["platform_id"] == "male-1")
    assert user["honor_title"] == "公司最靓的仔"
    assert client.get("/internal/game/users/missing/honors", headers=headers).status_code == 404


def test_random_event_participation_requires_completed_event_and_nonzero_rounds(context):
    repository, factory = context
    configure(repository)
    now = midnight(WEEK) + timedelta(hours=1)
    user = repository.find_user("male-1")
    donor = repository.find_user("male-2")
    for position, state, rounds in ((1, "ended", 1), (2, "ended", 0), (3, "dissolved", 10)):
        with factory.begin() as session:
            schedule = RandomEventScheduleRecord(event_date=now.date(), scheduled_at=now + timedelta(minutes=position))
            session.add(schedule)
            session.flush()
            event = RandomEventRecord(schedule_id=schedule.id, state=state, scene_name="剧情",
                signup_text="报名", formal_opening_text="开场", reward=1, target_rounds=1,
                signup_deadline=now, started_at=now, ended_at=now)
            session.add(event)
            session.flush()
            session.add(RandomEventParticipantRecord(event_id=event.id, user_id=user.id,
                role="自定义参演身份", rounds=rounds, joined_at=now))
            event_id = event.id
        if position == 1:
            inbound_id = message(repository, donor.platform_id, "/打赏", now)
            with factory.begin() as session:
                session.add(RandomEventTipRecord(event_id=event_id, sender_user_id=donor.id,
                    recipient_user_id=user.id, amount=12, inbound_message_id=inbound_id, created_at=now))
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    assert award(result, "performer_m")["score"] == 1
    assert award(result, "actor_m")["score"] == 12
    assert award(result, "tip_first_m")["winner_name"] == "米米"


@pytest.mark.parametrize("content", ["/我的称号", "/佩戴称号 0", "/装备称号 0", "/编辑称号 0"])
def test_honor_commands_remain_available_during_performance(context, content):
    repository, factory = context
    performance(factory, repository.find_user("male-1"), SETTLED, state="performing")
    service = CoreService(repository, GroupCommandHandler(repository))
    service.receive_inbound(InboundMessage("during-show", "male-1", content, SETTLED,
                                           source_type="group", chatroom_id="group-main"))
    with factory() as session:
        outbound = session.scalar(select(OutboundRecord))
        assert ("【我的称号】" if content == "/我的称号" else "已取消佩戴") in outbound.text


def test_disabled_announcement_retries_once_when_group_recovers(context):
    repository, factory = context
    configure(repository, announce=True)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).announcements_enabled = False
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    assert result["announced_at"] is None
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).announcements_enabled = True
    repository.run_honor_jobs(SETTLED)
    repository.run_honor_jobs(SETTLED)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1


def test_scheduled_announcement_uses_settled_result_once_after_restart(context, monkeypatch):
    repository, factory = context
    configure(repository, announce=True)
    chop(repository, factory, "male-1", 3)
    period = repository.settle_honors(WEEK, "admin", SETTLED)
    repository.run_honor_jobs(SETTLED)
    configure(repository, now=SETTLED, announce=True, announcement_time="11:30")
    chop(repository, factory, "male-2", 10)
    restarted = CoreRepository(factory)

    def fail_if_recalculated(*args, **kwargs):
        raise AssertionError("scheduled announcements must use settled awards")

    monkeypatch.setattr(restarted, "_honor_metrics", fail_if_recalculated)
    due = SETTLED + timedelta(hours=9)
    restarted.run_honor_jobs((due - timedelta(seconds=1)).astimezone(timezone.utc))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1
        assert session.get(HonorPeriodRecord, UUID(period["id"])).scheduled_announced_at is None
    restarted.run_honor_jobs(due.astimezone(timezone.utc))
    restarted.run_honor_jobs(due + timedelta(minutes=1))
    view = restarted.settle_honors(WEEK, "retry", due)
    assert view["announced_at"] == SETTLED.isoformat()
    assert view["scheduled_announced_at"] == due.isoformat()
    with factory() as session:
        announcements = list(session.scalars(select(OutboundRecord).order_by(OutboundRecord.created_at)))
        assert len(announcements) == 2
        assert "周一定时公告" not in announcements[0].text
        assert "周一定时公告" in announcements[1].text
        assert "公司最靓的仔：糯糯" in announcements[1].text
        assert session.scalar(select(func.count()).select_from(HonorAwardRecord).where(
            HonorAwardRecord.period_id == UUID(period["id"]))) == 29


@pytest.mark.parametrize("configured_time", ["08:45", "00:00"])
def test_scheduled_announcement_respects_configured_time(context, configured_time):
    repository, factory = context
    configure(repository, announce=True, announcement_time=configured_time)
    hour, minute = map(int, configured_time.split(":"))
    due = SETTLED + timedelta(hours=hour, minutes=minute)
    period = repository.settle_honors(WEEK, "admin", SETTLED)
    if due > SETTLED:
        repository.run_honor_jobs(due - timedelta(seconds=1))
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1
    repository.run_honor_jobs(due)
    repository.run_honor_jobs(due)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 2
        assert session.get(HonorPeriodRecord, UUID(period["id"])).scheduled_announced_at == due


def test_legacy_snapshot_defaults_to_nine_and_retries_when_group_recovers(context):
    repository, factory = context
    configure(repository, announce=True)
    with factory.begin() as session:
        config = repository._honor_config_for(session, WEEK)
        legacy = deepcopy(config.snapshot)
        legacy.pop("announcement_time")
        config.snapshot = legacy
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).announcements_enabled = False
    assert repository.get_honor_config(SETTLED)["configuration"]["announcement_time"] == "09:00"
    period = repository.settle_honors(WEEK, "admin", SETTLED)
    repository.run_honor_jobs(SETTLED + timedelta(hours=9))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 0
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).announcements_enabled = True
    recovered = SETTLED + timedelta(days=1)
    CoreRepository(factory).run_honor_jobs(recovered)
    repository.run_honor_jobs(recovered)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 2
        saved = session.get(HonorPeriodRecord, UUID(period["id"]))
        assert saved.announced_at == saved.scheduled_announced_at == recovered


def test_scheduled_announcement_failure_rolls_back_and_can_retry(context, monkeypatch):
    repository, factory = context
    configure(repository, announce=True)
    period = repository.settle_honors(WEEK, "admin", SETTLED)
    repository.run_honor_jobs(SETTLED)
    original = repository.enqueue_system_outbound

    def enqueue_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("scheduled announcement unavailable")

    monkeypatch.setattr(repository, "enqueue_system_outbound", enqueue_then_fail)
    due = SETTLED + timedelta(hours=9)
    with pytest.raises(RuntimeError):
        repository.run_honor_jobs(due)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1
        assert session.get(HonorPeriodRecord, UUID(period["id"])).scheduled_announced_at is None
    monkeypatch.setattr(repository, "enqueue_system_outbound", original)
    repository.run_honor_jobs(due)
    repository.run_honor_jobs(due)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 2


def test_disabled_honor_announcements_do_not_send_scheduled_message(context):
    repository, factory = context
    configure(repository, announce=False)
    period = repository.settle_honors(WEEK, "admin", SETTLED)
    repository.run_honor_jobs(SETTLED + timedelta(hours=9))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 0
        assert session.get(HonorPeriodRecord, UUID(period["id"])).scheduled_announced_at is None


def test_public_score_setting_hides_player_score_but_keeps_admin_snapshot(context):
    repository, factory = context
    rules = repository.get_honor_config(INITIAL)["configuration"]["rules"]
    next(rule for rule in rules if rule["key"] == "charm_m")["public_score"] = False
    configure(repository, rules=rules)
    chop(repository, factory, "male-1", 7)
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    assert award(result, "charm_m")["score"] == 7
    board = repository.honor_board(SETTLED)
    assert next(item for item in board["items"] if item["key"] == "charm_m")["score"] is None
    assert repository.my_honors("male-1", SETTLED)["items"][0]["score"] is None


def test_concurrent_settlement_announces_and_awards_once(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'concurrent-honors.db'}",
                           connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=main", INITIAL)
    repository.get_honor_config(INITIAL)
    configure(repository, announce=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda actor: repository.settle_honors(WEEK, actor, SETTLED),
                                    ["admin", "scheduler"]))
    assert results[0]["id"] == results[1]["id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HonorPeriodRecord)) == 1
        assert session.scalar(select(func.count()).select_from(HonorAwardRecord)) == 29
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 1
    repository.run_honor_jobs(SETTLED)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda offset: CoreRepository(factory).run_honor_jobs(SETTLED + timedelta(hours=9, seconds=offset)), [0, 1]))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord)) == 2
    engine.dispose()


def test_later_configuration_does_not_change_unsettled_previous_week(context):
    repository, factory = context
    configure(repository)
    chop(repository, factory, "male-1", 3)
    before = repository.preview_honors(WEEK, SETTLED)
    rules = repository.get_honor_config(SETTLED)["configuration"]["rules"]
    rule = next(rule for rule in rules if rule["key"] == "charm_m")
    rule.update(name="新称号名称", minimum=100)
    configure(repository, now=SETTLED, rules=rules)
    assert repository.preview_honors(WEEK, SETTLED)["preview_digest"] == before["preview_digest"]
    result = repository.settle_honors(WEEK, "admin", SETTLED)
    assert award(result, "charm_m")["name"] == "公司最靓的仔"
    assert award(result, "charm_m")["winner_name"] == "糯糯"
    later = repository.preview_honors(date(2026, 10, 19), SETTLED + timedelta(days=7))
    assert entry(later, "charm_m")["name"] == "新称号名称"
    assert entry(later, "charm_m")["minimum"] == 100


def test_multiple_honors_one_wear_and_cumulative_history_across_weeks(context):
    repository, factory = context
    configure(repository)
    user = repository.find_user("male-1")
    with factory.begin() as session:
        for offset in range(37):
            day = WEEK + timedelta(days=13-offset)
            session.add(DailyCheckinRecord(user_id=user.id, checkin_date=day, checked_in_at=midnight(day)))
    chop(repository, factory, "male-1", now=midnight(WEEK))
    chop(repository, factory, "male-1", now=SETTLED)
    repository.settle_honors(WEEK, "admin", SETTLED)
    personal = repository.my_honors("male-1", SETTLED)
    assert len(personal["items"]) == 4
    repository.wear_honor("male-1", 1, SETTLED)
    repository.wear_honor("male-1", 2, SETTLED)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HonorWearRecord)) == 1
    next_week = SETTLED + timedelta(days=7)
    repository.settle_honors(WEEK + timedelta(days=7), "admin", next_week)
    personal = repository.my_honors("male-1", next_week)
    assert personal["history_counts"] == {"checkin_king": 2, "checkin_god": 2, "charm_m": 2, "slacker": 2}
    assert all(item["total_wins"] == 2 for item in personal["items"])
    assert personal["equipped"] is None
    page = repository.honor_history(next_week, user_id=user.id, page_size=2)
    assert page["total"] == 8
    assert page["pages"] == 4


def test_default_disabled_period_does_not_publish_a_vacant_board(context):
    repository, _ = context
    repository.settle_honors(date(2026, 9, 28), "scheduler", midnight(WEEK))
    assert repository.honor_board(midnight(WEEK))["items"] == []
