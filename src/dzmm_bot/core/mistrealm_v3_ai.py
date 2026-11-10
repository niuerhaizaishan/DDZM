"""Bounded V3 decisions using the bot's hand and public board, never rival secrets."""
from copy import deepcopy
from random import Random
from . import mistrealm_v3_state as game
from .mistrealm_v3_scoring import definition


def visible_simulation(state,seat):
    s=deepcopy({k:v for k,v in state.items() if k not in ('action_log','action_frames','effect_cues')})
    s.update(action_log=[],action_frames=[],effect_cues=[])
    enemy=s['players'][1-seat]
    for zone in ('hand','deck'):
        enemy[zone]=[dict(id=f'unknown:{zone}:{i}',card='c081',owner=1-seat) for i in range(len(enemy[zone]))]
    # The bot knows its list, but not the order of its next draws.
    deck=s['players'][seat]['deck']
    revealed={uid for o in (s.get('pending') or {}).get('options',[]) for op in o['ops'] if op['kind']=='top' or (op['kind']=='bottom' and op.get('zone')=='deck') for uid in op['targets']}
    known={i:c for i,c in enumerate(deck) if c['id'] in revealed}
    unknown=sorted((c for c in deck if c['id'] not in revealed),key=lambda c:(c['card'],c['id']))
    Random(0).shuffle(unknown);remaining=iter(unknown)
    s['players'][seat]['deck']=[known[i] if i in known else next(remaining) for i in range(len(deck))]
    return s


def hand_value(player):
    return sum(3+min(10,definition(c)['power'])*.25+('spy' in definition(c)['abilities'])*2 for c in player['hand'])


def evaluate(s,seat):
    me,enemy=s['players'][seat],s['players'][1-seat]
    if s['phase']=='finished':return (1000 if s['winner']==seat else 0 if s['winner'] is None else -1000)+hand_value(me)
    score=sum(game.score_rows(s,seat));opponent=sum(game.score_rows(s,1-seat))
    resources=hand_value(me)-3*len(enemy['hand'])
    if enemy['passed'] and score>opponent:
        # Once enough strength is on the board, preserve the stronger remaining hand.
        return 200+resources
    return score-opponent+resources+2*(not me['leader_used'])+2*len(me['spells'])


def simulate(s,seat,move):
    return game.apply_action(s,seat,move['action'],move['payload'],s['server_time_ms'],Random(0))


def best_choice(s,seat):
    choices=[m for m in game.legal_moves(s,seat) if m['action']=='choose']
    return max(choices,key=lambda m:evaluate(simulate(s,seat,m),seat))


def pick_move(state,seat=1):
    s=visible_simulation(state,seat);moves=game.legal_moves(s,seat)
    if s.get('pending'):return best_choice(s,seat)
    me,enemy=s['players'][seat],s['players'][1-seat]
    score=sum(game.score_rows(s,seat));opponent=sum(game.score_rows(s,1-seat))
    passing=next((m for m in moves if m['action']=='pass'),None)
    if passing and enemy['passed'] and score>opponent:return passing
    # A losing early round can be conceded to retain cards for the next two rounds.
    spent=sum(e['kind']=='play' and e.get('seat')==seat and e.get('round')==s['round'] for e in state.get('action_log',[]))
    if passing and s['lives'][seat]>1 and opponent-score>=12 and spent>=2 and len(me['hand'])<=len(enemy['hand']):return passing
    candidates=[m for m in moves if m['action'] in ('play','leader')]
    if not candidates:return passing
    outcomes=[]
    for move in candidates:
        trial=simulate(s,seat,move)
        # Complete this action's own choices, not a speculative opponent turn.
        for _ in range(6):
            if not trial.get('pending') or trial['pending']['actor']!=seat:break
            trial=simulate(trial,seat,best_choice(trial,seat))
        outcomes.append((evaluate(trial,seat),move))
    return max(outcomes,key=lambda x:x[0])[1]


def mulligan(state,seat=1,limit=2):
    hand=state['players'][seat]['hand'];seen=set();ranked=[]
    for c in hand:
        d=definition(c);priority=0
        if 'muster' in d['abilities'] and c['card'] in seen:priority+=10
        if d['type']=='special' and d['persistent']:priority+=2
        if d['hero']:priority-=3
        if 'spy' in d['abilities']:priority-=4
        seen.add(c['card']);ranked.append((priority,-d['power'],c['id']))
    return [uid for priority,_,uid in sorted(ranked,reverse=True)[:limit] if priority>0]
