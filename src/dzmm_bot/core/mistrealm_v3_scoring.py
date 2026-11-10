"""Pure strength calculation; all conditions are recomputed from the current board."""
from .mistrealm_v3_cards import CARDS
from .mistrealm_expedition_cards import CARDS as EXPEDITION_CARDS
from .mistrealm_expedition_effects import condition as expedition_condition


def definition(card):
    d = CARDS[card['card']] if card['card'] in CARDS else EXPEDITION_CARDS[card['card']]
    return {**d, 'power': d['power'] + card['expedition_upgrade']} if card.get('expedition_upgrade') else d


def sealed(state, card):
    return card.get('sealed', False) or any(
        s['card'] == 'c120' and card['id'] in s.get('targets', [])
        for p in state['players'] if p for s in p.get('spells', []))


def _base_row_details(state, seat, row):
    p, enemy = state['players'][seat], state['players'][1-seat]
    cards = p['rows'][row]
    melee_aura = 3 if row == 0 and not p['hand'] and any(
        x['card'] == 'c098' and not sealed(state, x) for lane in p['rows'] for x in lane) else 0
    details = []
    for c in cards:
        d = definition(c); cid = c['card']; bonus = melee_aura
        others = [x for x in cards if x['id'] != c['id']]
        if not sealed(state, c):
            if cid in EXPEDITION_CARDS: bonus += expedition_condition(state,seat,row,c)
            if 'bond' in d['abilities'] and any(x['card'] == cid for x in others): bonus += 2
            if cid in ('c001','c010') and others: bonus += 2
            if cid == 'c003' and not others: bonus += 2
            if cid == 'c012' and p['spells']: bonus += 2
            if cid == 'c015' and not others: bonus += 4
            if cid == 'c110': bonus += 2*sum(definition(x)['faction']=='neutral' for lane in p['rows'] for x in lane)
            if cid == 'c016': bonus += 2*len(others)
            if cid == 'c017' and all(p['rows']): bonus += 3
            if cid == 'c018': bonus += 2*len(p['spells'])
            if cid == 'c021' and not enemy['rows'][0]: bonus += 2
            if cid == 'c055' and not p['rows'][2]: bonus += 4
            if cid == 'c035' and len(p['hand']) < len(enemy['hand']): bonus += 3
            if cid == 'c036': bonus += 2*p.get('melee_hits',0)
            if cid == 'c038': bonus += sum(definition(x)['type']=='unit' for x in p['discard'])//2
            if cid == 'c058': bonus += 2*state.get('move_count',0)
            if cid == 'c075': bonus += sum(count for owner in (p,enemy) for uid,count in owner.get('death_counts',{uid:1 for uid in owner['dead']}).items() if uid!=c['id'])
            if cid == 'c096': bonus += max(0,len(p['hand'])-len(enemy['hand']))
            if cid == 'c097': bonus += p['instant_count']
        intrinsic=bonus-melee_aura
        for owner in state['players']:
            for spell in owner['spells']:
                if c['id'] in spell.get('targets',[]):
                    if spell['card'] == 'c113': bonus -= 2
                    if spell['card']=='c118': bonus += 2
                    if spell['card'] == 'c120': bonus -= 2
        boost=c.get('boost',0)+c.get('uncapped_boost',0)
        power = d['power'] + boost + bonus - c.get('damage',0)
        details.append(dict(base=d['power'],boost=boost,condition=bonus,intrinsic=intrinsic,
                            damage=c.get('damage',0),shield=c.get('shield',0),sealed=bool(sealed(state,c)),
                            raw=power,power=max(0,power),hero=d['hero']))
    return details


def row_power_details(state, seat, row):
    details=_base_row_details(state,seat,row)
    # The traveler is a hero, so it cannot contribute to its own normal-unit count.
    count=sum(not d['hero'] and d['power']>6 for r in range(3)
              for d in _base_row_details(state,1-seat,r))
    for c,d in zip(state['players'][seat]['rows'][row],details):
        if c['card']=='c109' and not sealed(state,c):
            d['condition']+=3*count;d['intrinsic']+=3*count;d['raw']+=3*count;d['power']=max(0,d['raw'])
    return details


def score_rows(state, seat):
    return [sum(d['power'] for d in row_power_details(state,seat,r)) for r in range(3)]
