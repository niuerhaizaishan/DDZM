from __future__ import annotations

from dataclasses import dataclass, replace
from functools import total_ordering
from itertools import combinations
from typing import Mapping, Sequence


_SUIT_SYMBOLS = {
    "spades": "♠️",
    "hearts": "♥️",
    "clubs": "♣️",
    "diamonds": "♦️",
}
_CATEGORY_NAMES = (
    "高牌",
    "一对",
    "两对",
    "三条",
    "顺子",
    "同花",
    "葫芦",
    "四条",
    "同花顺",
)


class TexasHoldemRuleError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Card:
    suit: str
    rank: int

    def __post_init__(self) -> None:
        if self.suit not in _SUIT_SYMBOLS or not 2 <= self.rank <= 14:
            raise ValueError("invalid card")


@dataclass(frozen=True, slots=True)
class DealLayout:
    hole_cards: tuple[tuple[Card, Card], ...]
    burn_cards: tuple[Card, Card, Card]
    board: tuple[Card, Card, Card, Card, Card]

    @property
    def all_dealt_cards(self) -> tuple[Card, ...]:
        return tuple(card for hand in self.hole_cards for card in hand) + self.burn_cards + self.board


@total_ordering
@dataclass(frozen=True, slots=True)
class HandRank:
    category: int
    tiebreak: tuple[int, ...]

    @property
    def category_name(self) -> str:
        return _CATEGORY_NAMES[self.category]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, HandRank):
            return NotImplemented
        return (self.category, self.tiebreak) < (other.category, other.tiebreak)


@dataclass(frozen=True, slots=True)
class Pot:
    amount: int
    eligible_seats: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BettingPlayer:
    seat: int
    stack: int
    street_bet: int = 0
    folded: bool = False
    all_in: bool = False


@dataclass(frozen=True, slots=True)
class BettingRound:
    players: tuple[BettingPlayer, ...]
    current_bet: int
    last_full_raise: int
    current_seat: int | None
    acted_seats: frozenset[int]
    raise_open_seats: frozenset[int]

    def player(self, seat: int) -> BettingPlayer:
        try:
            return next(player for player in self.players if player.seat == seat)
        except StopIteration as exc:
            raise TexasHoldemRuleError("unknown_seat") from exc

    def to_call(self, seat: int) -> int:
        return max(0, self.current_bet - self.player(seat).street_bet)


@dataclass(frozen=True, slots=True)
class BettingActionResult:
    state: BettingRound
    committed: int
    round_complete: bool


def build_deck() -> tuple[Card, ...]:
    return tuple(
        Card(suit, rank)
        for suit in ("clubs", "diamonds", "hearts", "spades")
        for rank in range(2, 15)
    )


def format_card(card: Card) -> str:
    rank = {14: "1", 13: "K", 12: "Q", 11: "J"}.get(card.rank, str(card.rank))
    return f"{_SUIT_SYMBOLS[card.suit]}{rank}"


def deal_layout(deck: Sequence[Card], player_count: int) -> DealLayout:
    required = player_count * 2 + 8
    if player_count < 2 or len(deck) < required or len(set(deck)) != len(deck):
        raise TexasHoldemRuleError("invalid_deck")
    cursor = 0
    hands: list[list[Card]] = [[] for _ in range(player_count)]
    for _ in range(2):
        for hand in hands:
            hand.append(deck[cursor])
            cursor += 1
    first_burn = deck[cursor]
    flop = tuple(deck[cursor + 1 : cursor + 4])
    cursor += 4
    second_burn = deck[cursor]
    turn = deck[cursor + 1]
    cursor += 2
    third_burn = deck[cursor]
    river = deck[cursor + 1]
    return DealLayout(
        hole_cards=tuple((hand[0], hand[1]) for hand in hands),
        burn_cards=(first_burn, second_burn, third_burn),
        board=(flop[0], flop[1], flop[2], turn, river),
    )


def _five_card_rank(cards: Sequence[Card]) -> HandRank:
    ranks = sorted((card.rank for card in cards), reverse=True)
    counts: dict[int, int] = {}
    for rank in ranks:
        counts[rank] = counts.get(rank, 0) + 1
    grouped = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    flush = len({card.suit for card in cards}) == 1
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
    straight_high = next(
        (unique[index] for index in range(len(unique) - 4) if unique[index] - unique[index + 4] == 4),
        None,
    )
    if flush and straight_high is not None:
        return HandRank(8, (straight_high,))
    if grouped[0][0] == 4:
        four = grouped[0][1]
        return HandRank(7, (four, max(rank for rank in ranks if rank != four)))
    triples = sorted((rank for rank, count in counts.items() if count == 3), reverse=True)
    pairs = sorted((rank for rank, count in counts.items() if count >= 2), reverse=True)
    if triples:
        pair_candidates = [rank for rank in pairs if rank != triples[0]]
        if pair_candidates:
            return HandRank(6, (triples[0], pair_candidates[0]))
    if flush:
        return HandRank(5, tuple(ranks))
    if straight_high is not None:
        return HandRank(4, (straight_high,))
    if triples:
        kickers = sorted((rank for rank in ranks if rank != triples[0]), reverse=True)[:2]
        return HandRank(3, (triples[0], *kickers))
    exact_pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(exact_pairs) >= 2:
        high_pair, low_pair = exact_pairs[:2]
        kicker = max(rank for rank in ranks if rank not in {high_pair, low_pair})
        return HandRank(2, (high_pair, low_pair, kicker))
    if exact_pairs:
        pair = exact_pairs[0]
        kickers = sorted((rank for rank in ranks if rank != pair), reverse=True)[:3]
        return HandRank(1, (pair, *kickers))
    return HandRank(0, tuple(ranks))


def evaluate_best(cards: Sequence[Card]) -> HandRank:
    if not 5 <= len(cards) <= 7 or len(set(cards)) != len(cards):
        raise TexasHoldemRuleError("invalid_hand")
    return max(_five_card_rank(hand) for hand in combinations(cards, 5))


def build_side_pots(contributions: Mapping[int, int], folded_seats: set[int]) -> tuple[Pot, ...]:
    if any(amount < 0 for amount in contributions.values()):
        raise TexasHoldemRuleError("invalid_contribution")
    thresholds = sorted({amount for amount in contributions.values() if amount > 0})
    pots: list[Pot] = []
    previous = 0
    for threshold in thresholds:
        contributors = tuple(sorted(seat for seat, amount in contributions.items() if amount >= threshold))
        amount = (threshold - previous) * len(contributors)
        eligible = tuple(seat for seat in contributors if seat not in folded_seats)
        if amount:
            pots.append(Pot(amount=amount, eligible_seats=eligible))
        previous = threshold
    return tuple(pots)


def _next_from(seats: Sequence[int], after: int) -> int:
    ordered = tuple(sorted(seats))
    return next((seat for seat in ordered if seat > after), ordered[0])


def preflop_first_seat(active_seats: Sequence[int], button_seat: int) -> int:
    if len(active_seats) < 2:
        raise TexasHoldemRuleError("not_enough_players")
    if len(active_seats) == 2:
        return button_seat
    small_blind = _next_from(active_seats, button_seat)
    big_blind = _next_from(active_seats, small_blind)
    return _next_from(active_seats, big_blind)


def postflop_first_seat(active_seats: Sequence[int], button_seat: int) -> int:
    if len(active_seats) < 2:
        raise TexasHoldemRuleError("not_enough_players")
    return _next_from(active_seats, button_seat)


def _replace_player(players: tuple[BettingPlayer, ...], updated: BettingPlayer) -> tuple[BettingPlayer, ...]:
    return tuple(updated if player.seat == updated.seat else player for player in players)


def _actionable(player: BettingPlayer) -> bool:
    return not player.folded and not player.all_in and player.stack > 0


def _next_action_seat(state: BettingRound, after: int) -> int | None:
    candidates = {
        player.seat
        for player in state.players
        if _actionable(player)
        and (player.seat not in state.acted_seats or player.street_bet < state.current_bet)
    }
    if not candidates:
        return None
    ordered = sorted(player.seat for player in state.players)
    start = ordered.index(after)
    for offset in range(1, len(ordered) + 1):
        seat = ordered[(start + offset) % len(ordered)]
        if seat in candidates:
            return seat
    return None


def apply_betting_action(
    round_state: BettingRound,
    seat: int,
    action: str,
    amount: int | None = None,
) -> BettingActionResult:
    if round_state.current_seat != seat:
        raise TexasHoldemRuleError("not_your_turn")
    player = round_state.player(seat)
    if not _actionable(player):
        raise TexasHoldemRuleError("cannot_act")
    if action not in {"check", "call", "raise", "all_in", "fold"}:
        raise TexasHoldemRuleError("unknown_action")

    to_call = round_state.to_call(seat)
    committed = 0
    new_current_bet = round_state.current_bet
    new_last_raise = round_state.last_full_raise
    acted = set(round_state.acted_seats)
    raise_open = set(round_state.raise_open_seats)
    full_raise = False

    if action == "fold":
        updated = replace(player, folded=True)
    elif action == "check":
        if to_call:
            raise TexasHoldemRuleError("cannot_check")
        updated = player
    elif action == "call":
        if not to_call:
            raise TexasHoldemRuleError("nothing_to_call")
        committed = min(player.stack, to_call)
        updated = replace(
            player,
            stack=player.stack - committed,
            street_bet=player.street_bet + committed,
            all_in=committed == player.stack,
        )
    else:
        if action == "raise":
            if amount is None or isinstance(amount, bool):
                raise TexasHoldemRuleError("raise_amount_required")
            target = amount
            if seat not in raise_open:
                raise TexasHoldemRuleError("raise_not_reopened")
            if target <= round_state.current_bet:
                raise TexasHoldemRuleError("raise_too_small")
            committed = target - player.street_bet
            if committed > player.stack:
                raise TexasHoldemRuleError("insufficient_stack")
        else:
            committed = player.stack
            target = player.street_bet + committed
        if committed <= 0:
            raise TexasHoldemRuleError("empty_all_in")
        if target <= round_state.current_bet:
            if action == "raise":
                raise TexasHoldemRuleError("raise_too_small")
        else:
            raise_size = target - round_state.current_bet
            full_raise = raise_size >= round_state.last_full_raise
            if not full_raise and committed != player.stack:
                raise TexasHoldemRuleError("raise_too_small")
            new_current_bet = target
            if full_raise:
                new_last_raise = raise_size
        updated = replace(
            player,
            stack=player.stack - committed,
            street_bet=target,
            all_in=committed == player.stack,
        )

    acted.add(seat)
    raise_open.discard(seat)
    players = _replace_player(round_state.players, updated)
    if full_raise:
        acted = {seat}
        raise_open = {
            other.seat
            for other in players
            if other.seat != seat and _actionable(other)
        }
    state = BettingRound(
        players=players,
        current_bet=new_current_bet,
        last_full_raise=new_last_raise,
        current_seat=seat,
        acted_seats=frozenset(acted),
        raise_open_seats=frozenset(raise_open),
    )
    active_count = sum(not other.folded for other in players)
    next_seat = None if active_count <= 1 else _next_action_seat(state, seat)
    complete = next_seat is None
    state = replace(state, current_seat=next_seat)
    return BettingActionResult(state=state, committed=committed, round_complete=complete)
