from __future__ import annotations

from dataclasses import replace

import pytest

from dzmm_bot.core.texas_holdem import (
    BettingPlayer,
    BettingRound,
    Card,
    TexasHoldemRuleError,
    apply_betting_action,
    build_deck,
    build_side_pots,
    deal_layout,
    evaluate_best,
    format_card,
    postflop_first_seat,
    preflop_first_seat,
)


_SUITS = {"S": "spades", "H": "hearts", "C": "clubs", "D": "diamonds"}
_RANKS = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10}


def _cards(text: str) -> tuple[Card, ...]:
    return tuple(
        Card(_SUITS[token[0]], _RANKS.get(token[1:], int(token[1:]) if token[1:].isdigit() else 0))
        for token in text.split()
    )


def _round(
    *,
    stacks: dict[int, int],
    bets: dict[int, int] | None = None,
    current_bet: int = 0,
    last_full_raise: int = 2,
    current_seat: int = 1,
) -> BettingRound:
    street_bets = bets or {seat: 0 for seat in stacks}
    return BettingRound(
        players=tuple(
            BettingPlayer(
                seat=seat,
                stack=stack,
                street_bet=street_bets.get(seat, 0),
            )
            for seat, stack in sorted(stacks.items())
        ),
        current_bet=current_bet,
        last_full_raise=last_full_raise,
        current_seat=current_seat,
        acted_seats=frozenset(),
        raise_open_seats=frozenset(stacks),
    )


def test_display_ace_as_one_but_rank_wheel_below_six_high() -> None:
    wheel = evaluate_best(_cards("SA H2 C3 D4 S5 H9 CK"))
    six_high = evaluate_best(_cards("S2 H3 C4 D5 S6 H9 CK"))

    assert format_card(Card("spades", 14)) == "♠️1"
    assert wheel.category_name == "顺子"
    assert six_high > wheel


@pytest.mark.parametrize(
    ("cards", "category"),
    [
        ("SA SK SQ SJ ST H2 C3", "同花顺"),
        ("SA HA CA DA S2 H3 C4", "四条"),
        ("SA HA CA SK HK H3 C4", "葫芦"),
        ("SA SJ S8 S4 S2 H3 C5", "同花"),
        ("SA H2 C3 D4 S5 H9 CK", "顺子"),
        ("SA HA CA SK H8 D3 C4", "三条"),
        ("SA HA CK DK S8 H3 C4", "两对"),
        ("SA HA CK DQ S8 H3 C4", "一对"),
        ("SA HK CQ D9 S8 H3 C4", "高牌"),
    ],
)
def test_standard_hand_categories(cards: str, category: str) -> None:
    assert evaluate_best(_cards(cards)).category_name == category


def test_deal_layout_burns_before_each_board_street() -> None:
    layout = deal_layout(tuple(build_deck()), player_count=2)

    assert len(layout.hole_cards) == 2
    assert len(layout.burn_cards) == 3
    assert len(layout.board) == 5
    assert len(set(layout.all_dealt_cards)) == 12
    assert layout.hole_cards[0] == (Card("clubs", 2), Card("clubs", 4))
    assert layout.burn_cards[0] == Card("clubs", 6)
    assert layout.board[:3] == (Card("clubs", 7), Card("clubs", 8), Card("clubs", 9))


def test_side_pots_exclude_folded_players_but_keep_their_money() -> None:
    pots = build_side_pots({1: 100, 2: 60, 3: 20}, folded_seats={2})

    assert [(pot.amount, pot.eligible_seats) for pot in pots] == [
        (60, (1, 3)),
        (80, (1,)),
        (40, (1,)),
    ]


def test_heads_up_preflop_and_postflop_order_helpers() -> None:
    assert preflop_first_seat((1, 2), button_seat=1) == 1
    assert postflop_first_seat((1, 2), button_seat=1) == 2
    assert preflop_first_seat((1, 2, 3, 4), button_seat=1) == 4
    assert postflop_first_seat((1, 2, 3, 4), button_seat=1) == 2


def test_short_all_in_raises_call_amount_without_reopening_raise_rights() -> None:
    state = _round(
        stacks={1: 80, 2: 5, 3: 80},
        bets={1: 0, 2: 20, 3: 20},
        current_bet=20,
        last_full_raise=20,
        current_seat=1,
    )
    state = apply_betting_action(state, 1, "call").state
    state = replace(state, current_seat=2)
    state = apply_betting_action(state, 2, "all_in").state

    assert state.current_bet == 25
    assert 1 not in state.raise_open_seats
    assert state.to_call(1) == 5


def test_full_raise_reopens_action_and_moves_to_next_player() -> None:
    state = _round(stacks={1: 100, 2: 100, 3: 100}, current_seat=1)
    result = apply_betting_action(state, 1, "raise", 10)

    assert result.committed == 10
    assert result.state.current_bet == 10
    assert result.state.last_full_raise == 10
    assert result.state.current_seat == 2
    assert result.state.raise_open_seats == frozenset({2, 3})


def test_round_completes_only_after_every_actionable_player_matches() -> None:
    state = _round(stacks={1: 100, 2: 100}, current_seat=1)
    state = apply_betting_action(state, 1, "check").state
    result = apply_betting_action(state, 2, "check")

    assert result.round_complete
    assert result.state.current_seat is None


def test_illegal_check_fails_when_facing_a_bet() -> None:
    state = _round(
        stacks={1: 100, 2: 90}, bets={1: 0, 2: 10}, current_bet=10, current_seat=1
    )

    with pytest.raises(TexasHoldemRuleError) as exc_info:
        apply_betting_action(state, 1, "check")

    assert exc_info.value.code == "cannot_check"
