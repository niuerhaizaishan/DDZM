from datetime import datetime
from random import Random
from uuid import uuid4

from dzmm_bot.core.company_lottery import BEIJING
from dzmm_bot.core.random_event_vote import (
    break_tie,
    flatten_tiers,
    pick_distinct,
    pick_tiered,
    tally,
    tiered_pool,
    top_candidates,
)


def test_tiered_pool_prefers_never_performed_then_unplanned():
    pool = ["老戏", "排过了", "新的甲", "新的乙", "排过了二"]

    tiers = tiered_pool(
        pool,
        performed={"老戏"},
        planned={"排过了", "排过了二"},
    )

    # 第一档：没演过也没排过
    assert tiers[0] == ["新的甲", "新的乙"]
    # 第二档：演过但今天没排过
    assert tiers[1] == ["老戏"]
    # 第三档：今天已排过
    assert set(tiers[2]) == {"排过了", "排过了二"}


def test_tiered_pool_returns_every_scene_exactly_once():
    tiers = tiered_pool(["甲", "乙", "丙"], performed={"乙"}, planned=set())

    assert flatten_tiers(tiers) == ["甲", "丙", "乙"]
    assert sum(len(tier) for tier in tiers) == 3


def test_tiered_pool_skips_excluded_scenes():
    """被本次投票已选中的场景要排除，保证 3 个候选互不相同。"""
    tiers = tiered_pool(
        ["甲", "乙", "丙"],
        performed=set(),
        planned=set(),
        exclude={"甲"},
    )

    assert flatten_tiers(tiers) == ["乙", "丙"]


def test_tiered_pool_is_empty_without_scenes():
    assert tiered_pool([], performed=set(), planned=set()) == [[], [], []]


def test_pick_tiered_fills_the_top_tier_before_widening():
    """第一档管够时绝不碰第二档——这正是分档不能被拍平的原因。"""
    tiers = [["甲", "乙", "丙"], ["演过的"], ["排过的"]]

    picked = pick_tiered(tiers, 3, Random(7).randrange)

    assert sorted(picked) == ["丙", "乙", "甲"]


def test_pick_tiered_widens_when_the_top_tier_is_short():
    tiers = [["只此一个"], ["演过的", "也演过的"], ["排过的"]]

    picked = pick_tiered(tiers, 3, Random(3).randrange)

    assert "只此一个" in picked
    assert set(picked) - {"只此一个"} <= {"演过的", "也演过的"}
    assert "排过的" not in picked


def test_pick_distinct_returns_requested_count_and_keeps_order_of_pool():
    pool = ["甲", "乙", "丙", "丁"]

    picked = pick_distinct(pool, 3, Random(7).randrange)

    assert len(picked) == 3
    assert len(set(picked)) == 3
    assert all(item in pool for item in picked)


def test_pick_distinct_caps_at_the_pool_size():
    assert set(pick_distinct(["甲", "乙"], 5, Random(1).randrange)) == {"甲", "乙"}
    assert pick_distinct([], 3, Random(1).randrange) == []
    assert pick_distinct(["甲"], 0, Random(1).randrange) == []


def test_break_tie_prefers_the_least_performed_scene():
    first, second = uuid4(), uuid4()

    winner, reason = break_tie(
        [first, second],
        performances={first: 3, second: 1},
        authored_at={first: _moment(1), second: _moment(2)},
        randbelow=Random(1).randrange,
    )

    assert (winner, reason) == (second, "tie_perf")


def test_break_tie_prefers_the_later_submission_when_performances_match():
    """演出次数一样时，投稿晚的优先。"""
    first, second = uuid4(), uuid4()

    winner, reason = break_tie(
        [first, second],
        performances={first: 1, second: 1},
        authored_at={first: _moment(1), second: _moment(5)},
        randbelow=Random(1).randrange,
    )

    assert (winner, reason) == (second, "tie_time")


def test_break_tie_falls_back_to_the_random_source_when_all_else_is_equal():
    """三级都分不出来时必须真的去问随机源，而且只问一次。"""
    first, second, third = uuid4(), uuid4(), uuid4()
    calls: list[int] = []

    def randbelow(upper: int) -> int:
        calls.append(upper)
        return upper - 1

    winner, reason = break_tie(
        [first, second, third],
        performances={first: 2, second: 2, third: 2},
        authored_at={
            first: _moment(3),
            second: _moment(3),
            third: _moment(3),
        },
        randbelow=randbelow,
    )

    assert calls == [3]
    assert (winner, reason) == (third, "tie_random")


def test_tally_counts_every_candidate_including_zeroes():
    first, second = uuid4(), uuid4()

    counts = tally([first, second], [first, first, second])

    assert counts == {first: 2, second: 1}
    assert tally([first, second], []) == {first: 0, second: 0}


def test_top_candidates_returns_every_tied_leader():
    first, second, third = uuid4(), uuid4(), uuid4()
    counts = {first: 2, second: 2, third: 0}

    assert set(top_candidates(counts)) == {first, second}
    assert top_candidates({first: 0, second: 0}) == []


def _moment(minute: int) -> datetime:
    return datetime(2026, 9, 15, 12, minute, tzinfo=BEIJING)
