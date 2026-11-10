"""Small hooks allowing expedition cards to use the existing effect queue."""
from .mistrealm_expedition_cards import CARDS


def menu(state, seat, source):
    from . import mistrealm_v3_effects as e
    d=CARDS[source['card']];kind=d['effect'];n=d['amount'];p=state['players'][seat]
    own=e.units(state,seat);foes=e.units(state,1-seat)
    others=[c for c in own if c['id']!=source['id']]
    wounded=[c for c in foes if c.get('damage',0)>0]
    target=lambda cards,k,amount=0,**kw:e.target_options(cards,k,amount,**kw)
    if kind=='damage':return target(foes,'damage',n)
    if kind=='wounded_damage':return target(wounded,'damage',n)
    if kind=='boost':return target(others if d['type']=='unit' else own,'boost',n)
    if kind=='drain':return target(foes,'expedition_drain',n,source=source['id'])
    if kind=='revive':return e.revive_options(state,seat,ceiling=n)
    if kind=='recover':return target([c for c in p['discard'] if e.normal(c)],'recover')
    if kind in ('draw','rally','blood_draw'):
        ops=([e.op('damage',targets=[source['id']],amount=1)] if kind=='blood_draw' else [])
        ops.append(e.op('boost',targets=[c['id'] for c in others],amount=n) if kind=='rally' else e.op('draw',amount=n))
        return [e.option(d['text'],ops)]
    if kind in ('sacrifice_draw','sacrifice_boost'):
        return [e.option('牺牲 '+e.definition(c)['name'],[
            e.op('sacrifice',targets=[c['id']]),
            e.op('draw',amount=n) if kind=='sacrifice_draw' else e.op('boost',targets=[source['id']],amount=n)],c)
            for c in (others if d['type']=='unit' else own) if e.normal(c)]
    if kind in ('row_damage','row_boost','death_rally','end_boost'):
        side=1-seat if kind=='row_damage' else seat
        return [e.option(['近战','远程','攻城'][r],
            [e.op('mark_row',source=source['id'],row=r)] if d['persistent'] else
            [e.op('damage' if kind=='row_damage' else 'boost',targets=[c['id'] for c in state['players'][side]['rows'][r]],amount=n)],row=r)
            for r in range(3) if d['persistent'] or state['players'][side]['rows'][r]]
    if kind=='end_damage':return target(foes,'mark',source=source['id'])
    if kind=='wounded_all':return [e.option(d['text'],[e.op('damage',targets=[c['id'] for c in wounded],amount=n)])] if wounded else []
    if kind=='destroy_draw':return [e.option('摧毁 '+e.definition(c)['name'],[e.op('destroy_spell',targets=[c['id']]),e.op('draw',amount=1)],c) for owner in state['players'] for c in owner['spells']]
    if kind in ('move','enemy_move'):
        side=seat if kind=='move' else 1-seat
        return e.moves(state,side,[c for c in (others if kind=='move' else foes) if e.normal(c)],boost=n)
    if kind=='duel':return [e.option('决斗：'+e.definition(c)['name'],[e.op('expedition_duel',targets=[c['id']],source=source['id'],amount=n)],c) for c in foes]
    return []


def condition(state, seat, row, card):
    from . import mistrealm_v3_effects as e
    kind=CARDS.get(card['card'],{}).get('condition');p=state['players'][seat];foe=state['players'][1-seat]
    if kind=='grave':return sum(e.definition(c)['type']=='unit' for c in p['discard'])
    if kind=='fallen':return p['normal_deaths']
    if kind in ('wounded','wounded2'):return sum(c.get('damage',0)>0 for c in e.units(state,1-seat))*(2 if kind=='wounded2' else 1)
    if kind=='spells':return len(p['spells'])
    if kind=='alone':return 3 if len(p['rows'][row])==1 else 0
    if kind=='allies':return len(p['rows'][row])-1
    if kind=='opponents':return sum(e.normal(c) for c in foe['rows'][row])
    return 0


def on_death(state, seat, card, was_sealed):
    from . import mistrealm_v3_effects as e
    result=[];kind=CARDS.get(card['card'],{}).get('death')
    if kind and not was_sealed and not card.get('expedition_death_used'):
        card['expedition_death_used']=True
        result.append(e.op('draw',seat=card['owner'],amount=1) if kind=='draw' else
                      e.op('boost',seat=seat,targets=[c['id'] for c in e.units(state,seat)],amount=1))
    for spell in state['players'][seat]['spells']:
        if CARDS.get(spell['card'],{}).get('effect')=='death_rally' and spell.get('ticks',0)<3 and 'row' in spell:
            spell['ticks']=spell.get('ticks',0)+1
            result.append(e.op('boost',seat=seat,targets=[c['id'] for c in state['players'][seat]['rows'][spell['row']]],amount=1))
    return result


def end_play(state, seat):
    from . import mistrealm_v3_effects as e
    if not state.get('played_card'):return []
    result=[]
    for spell in state['players'][seat]['spells']:
        d=CARDS.get(spell['card'],{});kind=d.get('effect')
        if kind not in ('end_damage','end_boost') or spell.get('ticks',0)>=3:continue
        targets=spell.get('targets',[]) if kind=='end_damage' else [c['id'] for c in state['players'][seat]['rows'][spell['row']]]
        spell['ticks']=spell.get('ticks',0)+1
        result.append(e.op('damage' if kind=='end_damage' else 'boost',seat=seat,targets=targets,amount=d['amount'],cue_source=spell['card']))
    return result


def execute(state, seat, item):
    from . import mistrealm_v3_effects as e
    source=e.location(state,item['source']);target=e.location(state,item['targets'][0])
    if not source or not target:return
    n=item['amount']
    if item['kind']=='expedition_duel':
        e.damage(state,seat,item['targets'],n,source[2]['id'])
        e.damage(state,1-seat,[source[2]['id']],n,target[2]['id'])
    else:
        actual_targets=e.damage_targets(state,seat,item['targets']);before={}
        for uid in actual_targets:
            side,row,c=e.location(state,uid)
            detail=e.row_power_details(state,side,row)[state['players'][side]['rows'][row].index(c)]
            before[uid]=(c.get('damage',0),detail['power'])
        e.damage(state,seat,item['targets'],n,source[2]['id'])
        gain=sum(min(power,max(0,e.entity(state,uid).get('damage',0)-old)) for uid,(old,power) in before.items())
        e.execute(state,seat,e.op('boost',targets=[source[2]['id']],amount=gain))
