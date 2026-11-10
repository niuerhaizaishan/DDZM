"""Pure state machines for the Club card-table modules."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from random import Random

from .texas_holdem import Card, evaluate_best_five


GAMES = {"texas", "zhajinhua", "blackjack"}
PLAYER_LIMITS = {"texas": (2, 8), "zhajinhua": (2, 6), "blackjack": (2, 5)}
SUITS = ("clubs", "diamonds", "hearts", "spades")


def deck(rng: Random) -> list[list]:
    cards = [[suit, rank] for suit in SUITS for rank in range(2, 15)]
    rng.shuffle(cards)
    return cards


def _card(value) -> Card:
    return Card(str(value[0]), int(value[1]))


def _next(players: list[str], current: str, eligible: set[str]) -> str | None:
    if not eligible:
        return None
    start = players.index(current)
    for offset in range(1, len(players) + 1):
        candidate = players[(start + offset) % len(players)]
        if candidate in eligible:
            return candidate
    return None


def _award_single(state: dict, winner: str, label: str) -> dict:
    state["phase"] = "hand_finished"
    state["turn"] = None
    state["winners"] = [winner]
    state["result_label"] = label
    payouts = dict(state.get("chips", {}))
    payouts[winner] = payouts.get(winner, 0) + sum(state.get("contributions", {}).values())
    state["payouts"] = payouts
    return state


def new_hand(game: str, players: list[str], stake: int, rng: Random) -> dict:
    if game not in GAMES:
        raise ValueError("不支持的游戏")
    minimum, maximum = PLAYER_LIMITS[game]
    if not minimum <= len(players) <= maximum:
        raise ValueError(f"本玩法需要 {minimum}～{maximum} 人")
    if game == "texas":
        return _new_texas(players, stake, rng)
    if game == "zhajinhua":
        return _new_zhajinhua(players, stake, rng)
    return _new_blackjack(players, stake, rng)


def apply_action(game: str, state: dict, player: str, action: str, payload: dict) -> dict:
    if state.get("phase") != "playing":
        raise ValueError("当前牌局不能操作")
    if player != state.get("turn"):
        raise ValueError("还没轮到你")
    if game == "texas":
        return _texas_action(state, player, action, payload)
    if game == "zhajinhua":
        return _zhajinhua_action(state, player, action, payload)
    if game == "blackjack":
        return _blackjack_action(state, player, action)
    raise ValueError("不支持的游戏")


def public_view(game: str, state: dict, viewer: str) -> dict:
    value = {key: item for key, item in state.items() if key not in {"hands", "deck"}}
    hands = state.get("hands", {})
    if game == "blackjack":
        value["hands"] = {
            player: cards if player == viewer or state.get("phase") == "hand_finished" else [None] * len(cards)
            for player, cards in hands.items()
        }
    else:
        reveal = set(hands) if state.get("phase") == "hand_finished" else set()
        value["hands"] = {
            player: cards if player == viewer or player in reveal else [None] * len(cards)
            for player, cards in hands.items()
        }
    return value


def _new_texas(players: list[str], stake: int, rng: Random) -> dict:
    cards = deck(rng)
    hands = {player: [cards.pop(), cards.pop()] for player in players}
    button = players[0]
    small = button if len(players) == 2 else players[1]
    big = players[1] if len(players) == 2 else players[2]
    stack = stake if stake else 100
    small_blind = max(1, stack // 20)
    big_blind = small_blind * 2
    chips = {player: stack for player in players}
    street_bets = {player: 0 for player in players}
    contributions = {player: 0 for player in players}
    for player, blind in ((small, small_blind), (big, big_blind)):
        paid = min(chips[player], blind)
        chips[player] -= paid
        street_bets[player] += paid
        contributions[player] += paid
    turn = _next(players, big, set(players))
    return {
        "phase": "playing", "game": "texas", "players": players, "hands": hands,
        "deck": cards, "board": [], "street": "preflop", "button": button,
        "turn": turn, "chips": chips, "street_bets": street_bets,
        "contributions": contributions, "current_bet": big_blind,
        "minimum_raise": big_blind, "folded": [], "all_in": [], "acted": [],
        "pot": sum(contributions.values()), "last_action": "大小盲已入池",
    }


def _texas_action(state: dict, player: str, action: str, payload: dict) -> dict:
    if action not in {"check", "call", "raise", "all_in", "fold"}:
        raise ValueError("无效操作")
    folded, all_in, acted = map(set, (state["folded"], state["all_in"], state["acted"]))
    chips, bets, contributions = state["chips"], state["street_bets"], state["contributions"]
    to_call = max(0, state["current_bet"] - bets[player])
    if action == "fold":
        folded.add(player)
    elif action == "check":
        if to_call:
            raise ValueError("当前需要跟注或弃牌")
    elif action == "call":
        if not to_call:
            raise ValueError("当前无需跟注")
        paid = min(chips[player], to_call)
        chips[player] -= paid; bets[player] += paid; contributions[player] += paid
        if chips[player] == 0: all_in.add(player)
    else:
        if action == "all_in":
            target = bets[player] + chips[player]
        else:
            target = int(payload.get("amount", 0))
            if target < state["current_bet"] + state["minimum_raise"]:
                raise ValueError("加注金额不足")
            if target - bets[player] > chips[player]:
                raise ValueError("筹码不足")
        paid = chips[player] if action == "all_in" else target - bets[player]
        chips[player] -= paid; bets[player] += paid; contributions[player] += paid
        if target > state["current_bet"]:
            state["minimum_raise"] = max(state["minimum_raise"], target - state["current_bet"])
            state["current_bet"] = target
            acted = {player}
        if chips[player] == 0: all_in.add(player)
    acted.add(player)
    state.update(folded=sorted(folded), all_in=sorted(all_in), acted=sorted(acted))
    state["pot"] = sum(contributions.values())
    state["last_action"] = {"check": "过牌", "call": "跟注", "raise": "加注", "all_in": "全下", "fold": "弃牌"}[action]
    active = [item for item in state["players"] if item not in folded]
    if len(active) == 1:
        return _award_single(state, active[0], "其余玩家均已弃牌")
    actionable = {item for item in active if item not in all_in and chips[item] > 0}
    complete = not actionable or all(item in acted and bets[item] == state["current_bet"] for item in actionable)
    if complete:
        return _advance_texas(state)
    state["turn"] = _next(state["players"], player, actionable)
    return state


def _advance_texas(state: dict) -> dict:
    streets = {"preflop": ("flop", 3), "flop": ("turn", 1), "turn": ("river", 1)}
    active = [item for item in state["players"] if item not in state["folded"]]
    actionable = [item for item in active if item not in state["all_in"] and state["chips"][item] > 0]
    if state["street"] == "river" or len(actionable) < 2:
        while len(state["board"]) < 5:
            state["board"].append(state["deck"].pop())
        return _texas_showdown(state)
    next_street, count = streets[state["street"]]
    for _ in range(count): state["board"].append(state["deck"].pop())
    state["street"] = next_street
    state["street_bets"] = {item: 0 for item in state["players"]}
    state["current_bet"] = 0
    state["acted"] = []
    state["turn"] = _next(state["players"], state["button"], set(actionable))
    return state


def _texas_showdown(state: dict) -> dict:
    folded = set(state["folded"])
    contributions = state["contributions"]
    thresholds = sorted({amount for amount in contributions.values() if amount > 0})
    ranks = {
        player: evaluate_best_five([_card(card) for card in state["hands"][player] + state["board"]])[0]
        for player in state["players"] if player not in folded
    }
    payouts = dict(state["chips"])
    previous = 0
    for threshold in thresholds:
        contributors = [player for player, amount in contributions.items() if amount >= threshold]
        amount = (threshold - previous) * len(contributors)
        eligible = [player for player in contributors if player not in folded]
        best = max(ranks[player] for player in eligible)
        winners = [player for player in eligible if ranks[player] == best]
        share, remainder = divmod(amount, len(winners))
        for index, winner in enumerate(winners): payouts[winner] += share + (1 if index < remainder else 0)
        previous = threshold
    winners = [player for player, amount in payouts.items() if amount == max(payouts.values())]
    state.update(phase="hand_finished", turn=None, payouts=payouts, winners=winners,
                 hand_ranks={player: ranks[player].category_name for player in ranks}, result_label="摊牌结算")
    return state


def _zjh_rank(cards: list[list]) -> tuple:
    values = sorted((int(card[1]) for card in cards), reverse=True)
    counts = Counter(values)
    flush = len({card[0] for card in cards}) == 1
    wheel = values == [14, 3, 2]
    straight = wheel or (values[0] - values[2] == 2 and len(counts) == 3)
    high = 3 if wheel else values[0]
    if 3 in counts.values(): return (5, next(value for value, count in counts.items() if count == 3))
    if flush and straight: return (4, high)
    if flush: return (3, *values)
    if straight: return (2, high)
    if 2 in counts.values():
        pair = next(value for value, count in counts.items() if count == 2)
        kicker = next(value for value, count in counts.items() if count == 1)
        return (1, pair, kicker)
    return (0, *values)


def _zjh_rank_name(cards: list[list]) -> str:
    return ("散牌", "对子", "顺子", "金花", "同花顺", "豹子")[_zjh_rank(cards)[0]]


def _finish_zhajinhua(state: dict, winner: str, label: str) -> dict:
    result = _award_single(state, winner, label)
    result["hand_ranks"] = {
        player: _zjh_rank_name(cards) for player, cards in result["hands"].items()
    }
    return result


def _new_zhajinhua(players: list[str], stake: int, rng: Random) -> dict:
    cards = deck(rng)
    hands = {player: [cards.pop(), cards.pop(), cards.pop()] for player in players}
    stack = stake if stake else 50
    chips = {player: stack - 1 for player in players}
    contributions = {player: 1 for player in players}
    return {"phase": "playing", "game": "zhajinhua", "players": players, "hands": hands,
            "deck": cards, "turn": players[1 % len(players)], "dealer": players[0],
            "chips": chips, "contributions": contributions, "folded": [], "seen": [],
            "base_bet": 1, "round": 1, "pot": len(players), "last_action": "全员下底注"}


def _zhajinhua_action(state: dict, player: str, action: str, payload: dict) -> dict:
    if action not in {"look", "call", "raise", "fold", "compare"}:
        raise ValueError("无效操作")
    folded, seen = set(state["folded"]), set(state["seen"])
    if action == "look":
        seen.add(player); state["seen"] = sorted(seen); state["last_action"] = "看牌"
        return state
    if action == "fold":
        folded.add(player)
    else:
        multiplier = 2 if player in seen else 1
        amount = state["base_bet"] * multiplier
        if action == "raise": amount *= 2
        if action == "compare": amount *= 2
        paid = min(state["chips"][player], amount)
        if paid < amount: raise ValueError("筹码不足")
        state["chips"][player] -= paid; state["contributions"][player] += paid
        if action == "raise": state["base_bet"] *= 2
        if action == "compare":
            target = str(payload.get("target", ""))
            active = [item for item in state["players"] if item not in folded and item != player]
            if target not in active: raise ValueError("请选择仍在牌局中的玩家")
            if _zjh_rank(state["hands"][player]) > _zjh_rank(state["hands"][target]): folded.add(target)
            else: folded.add(player)
    state["folded"] = sorted(folded)
    state["pot"] = sum(state["contributions"].values())
    state["last_action"] = {"call": "跟注", "raise": "加注", "fold": "弃牌", "compare": "比牌"}[action]
    active = [item for item in state["players"] if item not in folded]
    if len(active) == 1: return _finish_zhajinhua(state, active[0], "炸金花胜出")
    if state["round"] >= 20:
        best = max(active, key=lambda item: _zjh_rank(state["hands"][item]))
        return _finish_zhajinhua(state, best, "达到轮次上限，自动比牌")
    next_player = _next(state["players"], player, set(active))
    if state["players"].index(next_player) <= state["players"].index(player): state["round"] += 1
    state["turn"] = next_player
    return state


def blackjack_total(cards: list[list]) -> tuple[int, bool]:
    values = [11 if card[1] == 14 else 10 if card[1] >= 10 else int(card[1]) for card in cards]
    total = sum(values); aces = sum(card[1] == 14 for card in cards)
    while total > 21 and aces: total -= 10; aces -= 1
    return total, bool(aces and total <= 21)


def _new_blackjack(players: list[str], stake: int, rng: Random) -> dict:
    cards = deck(rng)
    hands = {player: [cards.pop(), cards.pop()] for player in players}
    return {"phase": "playing", "game": "blackjack", "players": players, "hands": hands,
            "deck": cards, "turn": players[0], "stood": [], "busted": [],
            "contributions": {player: stake for player in players}, "pot": stake * len(players),
            "last_action": "玩家已发牌"}


def _blackjack_action(state: dict, player: str, action: str) -> dict:
    if action not in {"hit", "stand"}: raise ValueError("无效操作")
    if action == "hit":
        state["hands"][player].append(state["deck"].pop())
    total, _ = blackjack_total(state["hands"][player])
    if total > 21: state["busted"].append(player)
    if action == "stand" or total >= 21: state["stood"].append(player)
    state["last_action"] = {"hit": "要牌", "stand": "停牌"}[action]
    if action == "hit" and total < 21:
        state["turn"] = player
        return state
    waiting = [item for item in state["players"] if item not in state["stood"]]
    if waiting:
        state["turn"] = _next(state["players"], player, set(waiting))
        return state
    return _finish_blackjack(state)


def _finish_blackjack(state: dict) -> dict:
    totals = {player: blackjack_total(state["hands"][player])[0] for player in state["players"]}
    eligible = [player for player in state["players"] if totals[player] <= 21]
    payouts = {player: 0 for player in state["players"]}
    if not eligible:
        winners = []
        payouts = dict(state["contributions"])
        results = {player: "爆牌·退还" for player in state["players"]}
        label = "全员爆牌，本手退还"
    else:
        best = max(totals[player] for player in eligible)
        winners = [player for player in state["players"] if totals[player] == best]
        pot = sum(state["contributions"].values())
        share, remainder = divmod(pot, len(winners))
        for index, winner in enumerate(winners):
            payouts[winner] = share + (1 if index < remainder else 0)
        results = {
            player: ("爆牌" if totals[player] > 21 else
                     "胜" if len(winners) == 1 and player in winners else
                     "并列胜" if player in winners else "负")
            for player in state["players"]
        }
        label = f"最高 {best} 点"
    state.update(phase="hand_finished", turn=None, payouts=payouts, results=results,
                 winners=winners, totals=totals, result_label=label)
    return state
