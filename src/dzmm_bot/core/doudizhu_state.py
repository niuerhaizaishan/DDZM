"""Deterministic round transitions. Hidden state never goes directly to clients."""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from .doudizhu_rules import Pattern, choose_pattern, legal_plays, rank


def _stamp(now):
    if now.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return now.astimezone(timezone.utc).isoformat()


def new_round(deck: tuple[int, ...], first: int, now: datetime) -> dict:
    if len(deck) != 54 or any(type(c) is not int for c in deck) or set(deck) != set(range(54)):
        raise ValueError("牌堆必须包含 54 张不同的牌")
    if type(first) is not int or first not in range(3):
        raise ValueError("无效席位")
    return {
        'hands': [sorted(deck[i * 17:(i + 1) * 17]) for i in range(3)],
        'bottom': list(deck[51:]), 'phase': 'bidding', 'turn': first,
        'landlord': None, 'bid': 0, 'bidder': None, 'bid_count': 0,
        'passes': 0, 'previous': None, 'leader': None, 'table': [None] * 3,
        'play_counts': [0] * 3, 'multiplier': 1, 'trustees': [False] * 3,
        'deadline': _stamp(now + timedelta(seconds=15)), 'result': None, 'events': [],
    }


def apply_action(state: dict, seat: int, action: str, payload: dict, now: datetime) -> dict:
    if type(seat) is not int or seat not in range(3):
        raise ValueError("无效席位")
    if state['phase'] not in ('bidding', 'playing'):
        raise ValueError("本局当前不能操作")
    _stamp(now)
    if now >= datetime.fromisoformat(state['deadline']):
        raise ValueError("操作已超时，请刷新牌局")
    return _auto_pass_unplayable_trustees(_transition(state, seat, action, payload, now), now)


def _auto_pass_unplayable_trustees(state: dict, now: datetime) -> dict:
    result = state
    for _ in range(3):
        if result['phase'] != 'playing' or result['previous'] is None:
            break
        seat = result['turn']
        if not result['trustees'][seat]:
            break
        previous = Pattern(**{**result['previous'], 'cards': tuple(result['previous']['cards'])})
        if legal_plays(tuple(result['hands'][seat]), previous):
            break
        result = _transition(result, seat, 'pass', {}, now)
    return result


def _transition(state, seat, action, payload, now):
    result = deepcopy(state)
    if action in ('takeover', 'resume'):
        result['trustees'][seat] = action == 'takeover'
        return result
    if seat != state['turn']:
        raise ValueError("还没有轮到你")
    event = {'seq': len(result['events']) + 1, 'seat': seat, 'kind': action, 'at': _stamp(now)}
    if state['phase'] == 'bidding':
        score = payload.get('score')
        if action != 'bid' or type(score) is not int or score not in (0, 1, 2, 3) or (score and score <= state['bid']):
            raise ValueError("请选择更高的叫分或不叫")
        result['bid_count'] += 1
        if score:
            result['bid'], result['bidder'] = score, seat
        event['score'] = score
        result['turn'] = (seat + 1) % 3
        if score == 3 or result['bid_count'] == 3:
            if result['bid'] == 0:
                result['phase'] = 'redeal'
            else:
                landlord = result['bidder']
                result.update(phase='playing', landlord=landlord, turn=landlord, multiplier=result['bid'])
                result['hands'][landlord] = sorted(result['hands'][landlord] + result['bottom'])
    elif action == 'pass':
        if state['previous'] is None:
            raise ValueError("首家必须出牌")
        result['passes'] += 1
        result['table'][seat] = {'kind': 'pass', 'cards': []}
        result['turn'] = (seat + 1) % 3
        if result['passes'] == 2:
            result.update(previous=None, passes=0, turn=result['leader'], table=[None] * 3)
    elif action == 'play':
        selected = payload.get('cards')
        if not isinstance(selected, (list, tuple)):
            raise ValueError("请选择要出的牌")
        previous = Pattern(**{**state['previous'], 'cards': tuple(state['previous']['cards'])}) if state['previous'] else None
        play = choose_pattern(tuple(selected), previous)
        if not set(selected) <= set(state['hands'][seat]):
            raise ValueError("只能出自己的手牌")
        data = asdict(play)
        data['cards'] = list(play.cards)
        result.update(previous=data, leader=seat, passes=0, turn=(seat + 1) % 3)
        result['table'][seat] = data
        result['hands'][seat] = [c for c in state['hands'][seat] if c not in selected]
        result['play_counts'][seat] += 1
        event['play'] = data
        if play.kind in ('bomb', 'rocket'):
            result['multiplier'] *= 2
        if not result['hands'][seat]:
            landlord = result['landlord']
            farmers = [i for i in range(3) if i != landlord]
            spring = None
            if seat == landlord and all(result['play_counts'][i] == 0 for i in farmers):
                spring = 'spring'
            elif seat != landlord and result['play_counts'][landlord] == 1:
                spring = 'reverse_spring'
            if spring:
                result['multiplier'] *= 2
            result['result'] = {'winner': 'landlord' if seat == landlord else 'farmers',
                                'winners': [landlord] if seat == landlord else farmers, 'spring': spring}
            result['phase'] = 'finished'
    else:
        raise ValueError("无效操作")
    result['events'].append(event)
    result['deadline'] = (_stamp(now + timedelta(seconds=15 if result['phase'] == 'bidding' else 25))
                          if result['phase'] in ('bidding', 'playing') else None)
    return result


def apply_timeout(state: dict, now: datetime) -> dict:
    if state['phase'] not in ('bidding', 'playing'):
        return deepcopy(state)
    deadline = datetime.fromisoformat(state['deadline'])
    if now < deadline:
        return deepcopy(state)
    seat = state['turn']
    if state['phase'] == 'bidding':
        action, payload = 'bid', {'score': 0}
    elif state['previous']:
        action, payload = 'pass', {}
    else:
        action, payload = 'play', {'cards': [min(state['hands'][seat], key=lambda c: (rank(c), c))]}
    result = _transition(state, seat, action, payload, deadline)
    result['trustees'][seat] = True
    return _auto_pass_unplayable_trustees(result, deadline)
