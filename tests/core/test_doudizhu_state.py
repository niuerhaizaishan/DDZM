from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from dzmm_bot.core.doudizhu_state import apply_action, apply_timeout, new_round

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def playing():
    return apply_action(new_round(tuple(range(54)), 0, NOW), 0, 'bid', {'score': 3}, NOW)


def test_deal_and_bidding():
    state = new_round(tuple(range(54)), 1, NOW)
    assert [len(h) for h in state['hands']] == [17, 17, 17]
    assert state['bottom'] == [51, 52, 53]
    assert sorted(sum(state['hands'], []) + state['bottom']) == list(range(54))
    assert state['turn'] == 1
    state = apply_action(state, 1, 'bid', {'score': 1}, NOW)
    with pytest.raises(ValueError):
        apply_action(state, 2, 'bid', {'score': 1}, NOW)
    state = apply_action(state, 2, 'bid', {'score': 0}, NOW)
    state = apply_action(state, 0, 'bid', {'score': 2}, NOW)
    assert (state['phase'], state['landlord'], state['turn'], state['multiplier']) == ('playing', 0, 0, 2)
    assert len(state['hands'][0]) == 20
    assert json.loads(json.dumps(state)) == state


def test_all_pass_redeal_and_three_immediate():
    state = new_round(tuple(range(54)), 0, NOW)
    for seat in range(3):
        state = apply_action(state, seat, 'bid', {'score': 0}, NOW)
    assert state['phase'] == 'redeal'
    assert playing()['phase'] == 'playing'


def test_turns_passes_and_victory():
    state = playing()
    with pytest.raises(ValueError):
        apply_action(state, 0, 'pass', {}, NOW)
    state = apply_action(state, 0, 'play', {'cards': [0]}, NOW)
    state = apply_action(state, 1, 'pass', {}, NOW)
    state = apply_action(state, 2, 'pass', {}, NOW)
    assert state['turn'] == 0 and state['previous'] is None
    assert state['table'] == [None, None, None]
    state['hands'][0] = [1]
    state = apply_action(state, 0, 'play', {'cards': [1]}, NOW)
    assert state['result'] == {'winner': 'landlord', 'winners': [0], 'spring': 'spring'}
    assert state['multiplier'] == 6


def test_bombs_and_reverse_spring():
    state = playing()
    state = apply_action(state, 0, 'play', {'cards': [0, 1, 2, 3]}, NOW)
    assert state['multiplier'] == 6
    state['hands'][1] = [52, 53]
    state = apply_action(state, 1, 'play', {'cards': [52, 53]}, NOW)
    assert state['result'] == {'winner': 'farmers', 'winners': [1, 2], 'spring': 'reverse_spring'}
    assert state['multiplier'] == 24


def test_timeout_and_takeover():
    state = new_round(tuple(range(54)), 0, NOW)
    assert apply_timeout(state, NOW + timedelta(seconds=14)) == state
    state = apply_timeout(state, NOW + timedelta(seconds=15))
    assert state['turn'] == 1 and state['trustees'] == [True, False, False]
    state = playing()
    overdue = NOW + timedelta(seconds=100)
    state = apply_timeout(state, overdue)
    assert state['table'][0]['cards'] == [0]
    assert state['deadline'] == (NOW + timedelta(seconds=50)).isoformat()
    state = apply_timeout(state, overdue)
    assert state['table'][1]['kind'] == 'pass'
    state = apply_action(state, 0, 'resume', {}, NOW + timedelta(seconds=49))
    assert state['trustees'][0] is False
    assert 0 not in state['hands'][0]


def test_trustee_immediately_passes_when_no_legal_play():
    state = playing()
    state['hands'][1] = [17, 18, 19]
    state['trustees'][1] = True
    state = apply_action(state, 0, 'play', {'cards': [53]}, NOW)
    assert state['table'][1] == {'kind': 'pass', 'cards': []}
    assert state['turn'] == 2


def test_trustee_keeps_turn_when_a_legal_play_exists():
    state = playing()
    state['hands'][1] = [17]
    state['trustees'][1] = True
    state = apply_action(state, 0, 'play', {'cards': [0]}, NOW)
    assert state['table'][1] is None
    assert state['turn'] == 1


@pytest.mark.parametrize(('seat', 'action', 'payload'), [
    (1, 'play', {'cards': [17]}), (0, 'play', {'cards': [0, 0]}),
    (0, 'play', {'cards': [20]}), (0, 'play', {'cards': []}),
    (3, 'resume', {}), (True, 'resume', {}), (0, 'unknown', {}),
])
def test_illegal_actions_leave_input_unchanged(seat, action, payload):
    state = playing()
    original = deepcopy(state)
    with pytest.raises(ValueError):
        apply_action(state, seat, action, payload, NOW)
    assert state == original


def test_expired_and_finished_actions_rejected():
    with pytest.raises(ValueError):
        apply_action(playing(), 0, 'play', {'cards': [0]}, NOW + timedelta(seconds=25))
    state = playing()
    state['phase'] = 'finished'
    with pytest.raises(ValueError):
        apply_action(state, 0, 'resume', {}, NOW)


@pytest.mark.parametrize('deck', [tuple(range(53)), (0,) * 54, tuple(range(1, 55))])
def test_invalid_deck(deck):
    with pytest.raises(ValueError):
        new_round(deck, 0, NOW)
