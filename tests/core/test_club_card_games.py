from random import Random

import pytest

from dzmm_bot.core.club_card_games import (
    apply_action,
    blackjack_total,
    new_hand,
    public_view,
)


def test_texas_fold_settlement_preserves_all_bought_in_chips():
    state = new_hand("texas", ["a", "b"], 10, Random(4))

    finished = apply_action("texas", state, "a", "fold", {})

    assert finished["phase"] == "hand_finished"
    assert finished["winners"] == ["b"]
    assert sum(finished["payouts"].values()) == 20


def test_texas_hides_other_hole_cards_before_showdown():
    state = new_hand("texas", ["a", "b", "c"], 10, Random(3))

    view = public_view("texas", state, "a")

    assert view["hands"]["a"][0] is not None
    assert view["hands"]["b"] == [None, None]
    assert "deck" not in view


def test_zhajinhua_fold_awards_pot_and_returns_unspent_chips():
    state = new_hand("zhajinhua", ["a", "b"], 5, Random(8))

    finished = apply_action("zhajinhua", state, "b", "fold", {})

    assert finished["winners"] == ["a"]
    assert sum(finished["payouts"].values()) == 10


def test_blackjack_total_handles_soft_ace():
    assert blackjack_total([["spades", 14], ["clubs", 6]]) == (17, True)
    assert blackjack_total([["spades", 14], ["clubs", 6], ["hearts", 10]]) == (17, False)


def test_blackjack_is_pvp_and_hit_keeps_the_players_turn():
    state = new_hand("blackjack", ["a", "b"], 10, Random(1))
    assert "dealer" not in state
    state["hands"]["a"] = [["spades", 4], ["clubs", 5]]
    state["hands"]["b"] = [["spades", 9], ["clubs", 8]]
    state["deck"] = [["diamonds", 2], ["hearts", 3]]

    state = apply_action("blackjack", state, "a", "hit", {})
    assert state["turn"] == "a"
    assert len(state["hands"]["a"]) == 3
    state = apply_action("blackjack", state, "a", "hit", {})
    assert state["turn"] == "a"
    assert len(state["hands"]["a"]) == 4
    state = apply_action("blackjack", state, "a", "stand", {})
    assert state["turn"] == "b"
    state = apply_action("blackjack", state, "b", "stand", {})

    assert state["phase"] == "hand_finished"
    assert state["winners"] == ["b"]
    assert state["results"] == {"a": "负", "b": "胜"}
    assert state["payouts"] == {"a": 0, "b": 20}


def test_blackjack_tied_winners_split_the_pvp_pool():
    state = new_hand("blackjack", ["a", "b", "c"], 10, Random(2))
    state["hands"] = {
        "a": [["spades", 10], ["clubs", 10]],
        "b": [["hearts", 13], ["diamonds", 10]],
        "c": [["spades", 13], ["clubs", 9]],
    }

    state = apply_action("blackjack", state, "a", "stand", {})
    state = apply_action("blackjack", state, "b", "stand", {})
    state = apply_action("blackjack", state, "c", "stand", {})

    assert state["winners"] == ["a", "b"]
    assert state["payouts"] == {"a": 15, "b": 15, "c": 0}
    assert state["results"] == {"a": "并列胜", "b": "并列胜", "c": "负"}


def test_blackjack_all_bust_refunds_the_pvp_pool():
    state = new_hand("blackjack", ["a", "b"], 10, Random(3))
    state["hands"] = {
        "a": [["spades", 13], ["clubs", 12]],
        "b": [["hearts", 13], ["diamonds", 12]],
    }
    state["deck"] = [["clubs", 2], ["spades", 2]]

    state = apply_action("blackjack", state, "a", "hit", {})
    state = apply_action("blackjack", state, "b", "hit", {})

    assert state["phase"] == "hand_finished"
    assert state["winners"] == []
    assert state["payouts"] == {"a": 10, "b": 10}
    assert state["results"] == {"a": "爆牌·退还", "b": "爆牌·退还"}


def test_wrong_turn_is_rejected():
    state = new_hand("zhajinhua", ["a", "b", "c"], 5, Random(2))
    with pytest.raises(ValueError, match="还没轮到你"):
        apply_action("zhajinhua", state, "a", "call", {})
