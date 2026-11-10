"""V3 effects, finite choices and simultaneous death resolution.

The work queue is JSON data so a choice survives reconnects and server restarts.
"""
from itertools import combinations
from . import mistrealm_expedition_effects as expedition
from .mistrealm_v3_feedback import board_snapshot, record_changes
import random
from .mistrealm_v3_cards import ROW_CAPACITY, SPELL_CAPACITY
from .mistrealm_v3_scoring import definition, sealed, row_power_details


def units(state, seat):
    return [c for row in state['players'][seat]['rows'] for c in row]


def location(state, uid):
    for seat,p in enumerate(state['players']):
        for row,cards in enumerate(p['rows']):
            for c in cards:
                if c['id']==uid: return seat,row,c
    return None


def entity(state, uid):
    found=location(state,uid)
    if found: return found[2]
    for p in state['players']:
        for zone in ('hand','deck','discard','spells','resolving'):
            for c in p[zone]:
                if c['id']==uid:return c
    return None


def normal(c):
    return definition(c)['type']=='unit' and not definition(c)['hero']


def reusable(c):
    return normal(c) and 'spy' not in definition(c)['abilities']


def reset(c):
    for key in ('boost','damage','shield','sealed','targets','row','entered','sacrificed','entry_draws','ticks','uncapped_boost'):
        c.pop(key,None)


def detach_targets(state,c):
    for p in state['players']:
        for spell in p['spells']:
            if c['id'] in spell.get('targets',[]):spell['targets'].remove(c['id'])


def discard(state,c):
    detach_targets(state,c)
    reset(c)
    owner=state['players'][c['owner']]
    owner['discard'].append(c);owner['discarded_this_round']=True


def draw(p,n):
    n=min(n,len(p['deck']))
    for _ in range(n):p['hand'].append(p['deck'].pop())
    return n


def op(kind, **values):
    return dict(kind=kind,**values)


def option(label,ops,card=None,row=-1):
    value=dict(label=label,ops=ops,row=row)
    if card is not None:value['card']=dict(card)
    return value


def target_options(cards, kind, amount=0, **extra):
    return [option(definition(c)['name'],[op(kind,targets=[c['id']],amount=amount,**extra)],c) for c in cards]


def groups(cards,maximum=2):
    return [list(group) for n in range(1,min(maximum,len(cards))+1) for group in combinations(cards,n)]


def label(cards):
    return ' + '.join(definition(c)['name'] for c in cards)


def moves(state,seat,cards,boost=0,own_row=None):
    return [option(f"{definition(c)['name']} → {['近战','远程','攻城'][r]}",
                   [op('move',targets=[c['id']],row=r,amount=boost)],c,r)
            for c in cards for r in range(3) if (own_row is None or r==own_row)
            and location(state,c['id'])[1]!=r and len(state['players'][seat]['rows'][r])<ROW_CAPACITY]


def summon_options(state,seat,group=None,ceiling=None,include_spy=False):
    p=state['players'][seat]
    return [option(f"{definition(c)['name']} → {['近战','远程','攻城'][r]}",
                   [op('summon',targets=[c['id']],row=r)],c,r)
            for c in p['deck'] if (normal(c) if include_spy else reusable(c))
            and (group is None or c['card'] in group)
            and (ceiling is None or definition(c)['power']<=ceiling)
            for r in definition(c)['rows'] if len(p['rows'][r])<ROW_CAPACITY]


def revive_options(state,seat,ceiling=3,deploy=False):
    p=state['players'][seat]
    return [option(f"复活 {definition(c)['name']} → {['近战','远程','攻城'][r]}",
                   [op('revive',targets=[c['id']],row=r,deploy=deploy)],c,r)
            for c in p['discard'] if reusable(c) and definition(c)['power']<=ceiling
            and c.get('revived_round')!=state['round']
            for r in definition(c)['rows'] if len(p['rows'][r])<ROW_CAPACITY]


def _menu(state,seat,source):
    """Choices for this card now. Empty unit menus simply skip deployment effects."""
    cid=source['card'];p=state['players'][seat];enemy=state['players'][1-seat]
    own=units(state,seat);foes=units(state,1-seat)
    others=[c for c in own if c['id']!=source['id']]
    here=location(state,source['id']);row=here[1] if here else -1
    def targets(cards,kind,n=0,**extra):return target_options(cards,kind,n,**extra)
    if cid in expedition.CARDS:return expedition.menu(state,seat,source)
    if cid=='c004':return targets(others,'boost',3)
    if cid=='c005':return [option(label(g),[op('boost',targets=[c['id'] for c in g],amount=2)],g[0]) for g in groups(others)]
    if cid=='c007':return targets(enemy['rows'][1],'damage',3)
    if cid=='c011':return targets(foes,'damage',2)
    if cid=='c013':return [option(definition(c)['name'],[op('boost',targets=[c['id']],amount=3),op('draw',amount=1)],c) for c in own]
    if cid in ('c014','c054','c074'):
        return [option(['近战','远程','攻城'][r],[op('mark_row',source=source['id'],row=r)],row=r) for r in range(3)]
    if cid=='c019':return summon_options(state,seat,ceiling=3,include_spy=True)
    if cid=='c020':
        spells=[c for c in p['discard'] if definition(c)['persistent']]
        return [option('回手：'+definition(a)['name']+'；回牌库：'+definition(b)['name'],
                       [op('recover',targets=[a['id']]),op('return_deck',targets=[b['id']])],a)
                for a in spells for b in spells if a['id']!=b['id']]
    if cid=='c022':return targets(foes,'damage',2)
    if cid=='c027':return targets(foes,'damage',2,hunter_followup=True)
    if cid=='c028':return [option(label(g),[op('damage',targets=[c['id'] for c in g],amount=1)],g[0]) for g in groups(foes)]
    if cid in ('c029','c070','c105'):return revive_options(state,seat)
    if cid=='c080':return [option('抽3张牌，再将1张手牌置底',[op('draw',amount=3),op('bottom_hand_choice')])] if p['deck'] or p['hand'] else []
    if cid=='c048':return [option(label(g),[op('boost',targets=[c['id'] for c in g],amount=2)],g[0]) for g in groups(own)]
    if cid=='c050':return moves(state,seat,[c for c in others if normal(c)])+moves(state,1-seat,[c for c in foes if normal(c)])
    if cid=='c051':return revive_options(state,seat,ceiling=4,deploy=True)
    if cid=='c030':
        low=[c for r in range(3) for c,d in zip(enemy['rows'][r],row_power_details(state,1-seat,r)) if normal(c) and d['power']<=2]
        return targets(low,'bounce')
    if cid in ('c031','c040'):
        if source.get('resource_used'):return []
        options=targets([c for c in p['discard'] if reusable(c) and definition(c)['power']<=4],'recover',source=source['id'])
        if cid=='c040':
            for o in options:o['ops'].append(op('draw',amount=1))
        return options
    if cid=='c032':return targets(foes,'damage',3)
    if cid=='c033':return targets([c for c in own+foes if normal(c)],'bounce')
    if cid=='c034':return [option('标记敌方当前全部单位',[op('mark',source=source['id'],targets=[c['id'] for c in foes])])] if foes else []
    if cid=='c037':return [option(definition(c)['name'],[op('deploy',source=c['id'])],c) for c in others if normal(c)]
    if cid=='c039':return [option(definition(c)['name'],[op('seal',targets=[c['id']]),op('damage',targets=[c['id']],amount=3)],c) for c in foes]
    if cid in ('c045','c046','c047'):return summon_options(state,seat,['c045','c046','c047'])
    if cid in ('c107','c055'):return moves(state,1-seat,[c for c in foes if normal(c)])
    if cid=='c057' and here:
        return [option(['近战','远程','攻城'][r],[op('damage',targets=[c['id'] for c in lane],amount=min(4,len(p['rows'][row])))],row=r) for r,lane in enumerate(enemy['rows']) if lane]
    if cid=='c053':
        options=moves(state,1-seat,[c for c in foes if normal(c)])
        for o in options:o['ops'].append(op('damage',targets=[o['card']['id']],amount=4))
        return moves(state,seat,[c for c in own if normal(c)],boost=4)+options
    if cid=='c059':
        options=moves(state,1-seat,foes)
        for o in options:o['ops'].append(op('damage',targets=[o['card']['id']],amount=2))
        return moves(state,seat,own,boost=2)+options
    if cid=='c060':return targets(p['spells']+enemy['spells'],'bounce_spell')+([option('抽2张牌',[op('draw',amount=2)])] if p['deck'] else [])
    if cid in ('c061','c062','c063'):return summon_options(state,seat,['c061','c062','c063'])
    if cid in ('c064','c065','c066'):return summon_options(state,seat,['c064','c065','c066'])
    if cid=='c069':return [option('牺牲 '+definition(c)['name'],[op('sacrifice',targets=[c['id']]),op('draw',amount=2)],c) for c in others if normal(c)]
    if cid=='c072':return [option(['近战','远程','攻城'][r],[op('damage',targets=[c['id'] for c in p['rows'][r]+enemy['rows'][r]],amount=2)],row=r) for r in range(3)]
    if cid=='c073':return [option('牺牲 '+definition(a)['name']+' → 敌方全场各受3点伤害',[op('sacrifice',targets=[a['id']]),op('damage',targets=[b['id'] for b in foes],amount=3)],a) for a in own if normal(a)] if foes else []
    if cid=='c076':return [option('吞噬 '+label(list(g)),[op('devour',source=source['id'],targets=[c['id'] for c in g])],g[0]) for g in combinations([c for c in others+foes if normal(c)],2)]
    if cid=='c077':return [option('洗回牌库：'+label(g),[op('return_deck',targets=[c['id']]) for c in g]+[op('boost',targets=[source['id']],amount=len(g))],g[0]) for g in groups([c for c in p['discard'] if normal(c)],3)]
    if cid=='c078' and len(own)<len(foes):return summon_options(state,seat,ceiling=3)
    if cid=='c079':
        return targets(p['discard'],'recycle',count=3) if p['discard'] else ([option('抽1张牌',[op('draw',amount=1)])] if p['deck'] else [])
    if cid=='c083':return targets(own+foes,'damage',3) if p['instant_count']>0 else []
    if cid=='c084':return [option('加入手牌：'+definition(c)['name'],[op('top',targets=[c['id']])],c) for c in p['deck'][-2:]]
    if cid=='c085':
        if source.get('exchange_used'):return []
        return [option('回手：'+definition(b)['name']+'；弃置：'+definition(a)['name'],
                       [op('exchange',source=source['id'],targets=[a['id'],b['id']])],b)
                for a in p['hand'] for b in p['discard'] if not definition(a)['hero'] and not definition(b)['hero']]
    if cid=='c086' and p['instant_count']>0:return [option(label(list(g)),[op('boost',targets=[c['id'] for c in g],amount=2)],g[0]) for g in combinations(own,2)]
    if cid=='c087':return targets(p['spells'],'bounce_spell')
    if cid=='c090':return targets([c for c in p['discard'] if not c.get('ritualist_used') and definition(c)['type']=='special' and not definition(c)['persistent'] and menu(state,seat,c)],'recast')
    if cid in ('c091','c099'):
        if source.get('resource_used'):return []
        options=targets([c for c in p['discard'] if definition(c)['type']=='special' and not definition(c)['persistent'] and not c.get('recovered')],'recover',source=source['id'])
        if cid=='c099':
            for o in options:o['ops'].append(op('draw',amount=1))
        return options
    if cid=='c092':return [option('牺牲 '+definition(c)['name'],[op('sacrifice',targets=[c['id']]),op('recover_choice')],c) for c in others if normal(c)]
    if cid=='c093':return [option('抽2张牌',[op('draw',amount=2)])] if p['deck'] and p.get('prayer_round')!=state['round'] else []
    if cid=='c094':return [option('放置沉舟回响',[])]
    if cid=='c100':return [option(definition(c)['name'],[op('boost',targets=[c['id']],amount=3),op('draw',amount=1)],c) for c in own]
    if cid=='c101':return targets(p['spells']+enemy['spells'],'destroy_spell')
    if cid=='c103':return targets(foes,'damage',2)
    if cid=='c104':return [option('牺牲 '+definition(c)['name'],[op('sacrifice',targets=[c['id']]),op('boost',targets=[source['id']],amount=2)],c) for c in others if normal(c)]
    if cid=='c106':return [option('置于牌底：'+definition(c)['name'],[op('bottom',targets=[c['id']],zone='deck')],c) for c in reversed(p['deck'][-3:])]
    if cid=='c052':return moves(state,seat,[c for c in own if normal(c)])+moves(state,1-seat,[c for c in foes if normal(c)])
    if cid=='c111':return targets(foes,'damage',4)
    if cid=='c112':return [option('牺牲 '+definition(c)['name'],[op('sacrifice',targets=[c['id']]),op('draw',amount=2)],c) for c in own if normal(c)]
    if cid=='c114':return [option(definition(c)['name'],[op('mark',source=source['id'],targets=[c['id']])],c) for c in foes] if not enemy['passed'] else []
    if cid in ('c113','c118'):
        pools=enemy['rows'] if cid=='c113' else [own]
        return [option(label(g),[op('mark',source=source['id'],targets=[c['id'] for c in g])],g[0]) for pool in pools for g in groups(pool,3)]
    if cid=='c115':
        # Ordered pairs allow the caster to select which target receives the marked-row bonus.
        return [option(label(g),[op('damage',targets=[c['id'] for c in g],amount=2)],g[0]) for g in groups(foes) for g in ([g,list(reversed(g))] if len(g)==2 else [g])]
    if cid=='c116':return targets([c for c in p['discard'] if not definition(c)['hero']],'return_deck')
    if cid=='c117':return targets([c for c in own if normal(c)],'bounce')
    if cid=='c119':return [option('双方全场各受2点伤害',[op('damage',targets=[c['id'] for c in own+foes],amount=2)])] if own or foes else []
    if cid=='c120':return [option(definition(c)['name'],[op('mark',source=source['id'],targets=[c['id']])],c) for c in foes]
    return []


def menu(state,seat,source):
    options=_menu(state,seat,source)
    if definition(source)['type']=='unit':
        for o in options:
            for effect in o['ops']:
                if effect['kind']=='damage':effect['damage_source']=source['id']
    for choice in options:
        for effect in choice['ops']:effect['cue_source']=source['card']
    return options


def settle(state):
    """Remove each simultaneously lethal batch before reevaluating conditions."""
    deaths=[]
    while True:
        batch=[(seat,row,c,bool(sealed(state,c))) for seat in (0,1) for row in range(3)
               for c,d in zip(state['players'][seat]['rows'][row],row_power_details(state,seat,row)) if d['raw']<=0 or c.get('sacrificed')]
        if not batch:break
        for seat,row,c,is_sealed in batch:
            state['players'][seat]['rows'][row].remove(c)
            deaths.append((seat,c['entered'],dict(c),is_sealed))
            p=state['players'][seat]
            counts=p.setdefault('death_counts',{uid:1 for uid in p['dead']})
            counts[c['id']]=counts.get(c['id'],0)+1
            if normal(c):
                p['normal_deaths']+=1
                if c['id'] not in p['dead_normal']:p['dead_normal'].append(c['id'])
            if c['id'] not in p['dead']:p['dead'].append(c['id'])
            state['events'].append(f"{definition(c)['name']} 被献祭" if c.get('sacrificed') else f"{definition(c)['name']} 战力归零，阵亡")
            discard(state,c)
    queued=[]
    for seat,_,old,is_sealed in sorted(deaths,key=lambda x:(x[0]!=state['actor'],x[1])):
        c=entity(state,old['id'])
        queued.extend(expedition.on_death(state,seat,c,is_sealed))
        if old.get('sacrificed'):
            for spell in state['players'][seat]['spells']:
                if spell['card']=='c074':
                    queued.append(op('boost',seat=seat,targets=[u['id'] for u in state['players'][seat]['rows'][spell['row']]],amount=2))
        if not is_sealed and c['card'] in ('c064','c065','c066'):
            queued.append(op('return_deck',seat=c['owner'],targets=[c['id']]))
        if not is_sealed and c['card']=='c067' and c.get('death_round')!=state['round']:
            c['death_round']=state['round'];queued.append(op('draw',seat=c['owner'],amount=2,cue_source=c['card']))
        if not is_sealed and c['card']=='c071':
            queued.append(op('death_boost',seat=seat,source=c['id']))
    state['work'][0:0]=queued


def damage_targets(state,seat,targets):
    guards=[c for c in units(state,1-seat) if c['card']=='c102' and not sealed(state,c)]
    guard=min(guards,key=lambda c:c.get('entered',0)) if guards else None
    result=[]
    for uid in targets:
        found=location(state,uid)
        if not found:continue
        target=guard['id'] if guard and found[0]!=seat else uid
        if target not in result:result.append(target)
    return result


def damage(state,seat,targets,amount,source=None):
    attacker=entity(state,source) if source else None
    targets=damage_targets(state,seat,targets)
    for uid in targets:
        found=location(state,uid)
        if not found:continue
        side,row,c=found;n=amount
        for owner in state['players']:
            for spell in owner['spells']:
                if spell['card']=='c034' and uid in spell.get('targets',[]) and n>0:
                    n+=2;spell['targets'].remove(uid)
        absorbed=min(n,c.get('shield',0));c['shield']=c.get('shield',0)-absorbed
        dealt=n-absorbed;c['damage']=c.get('damage',0)+dealt
        if dealt>0 and attacker and normal(attacker) and side!=seat and row==0 and normal(c):
            state['players'][seat]['melee_hits']=state['players'][seat].get('melee_hits',0)+1
        state['events'].append(f"{definition(c)['name']} 受到 {dealt} 点伤害（护盾抵消 {absorbed}）")

    return targets


def record_entry(state,seat,c,row):
    state['entered_action'].append(dict(id=c['id'],seat=seat,row=row))
    if normal(c):
        targets=[u['id'] for u in state['players'][1-seat]['rows'][row] if u['card']=='c041' and not sealed(state,u)]
        execute(state,1-seat,op('boost',targets=targets,amount=1,uncapped=True))


def put(state,seat,c,row):
    if len(state['players'][seat]['rows'][row])>=ROW_CAPACITY:raise ValueError('该战列已满（4/4）')
    state['entry_id']+=1;c['entered']=state['entry_id']
    state['players'][seat]['rows'][row].append(c)
    record_entry(state,seat,c,row)


def remove_unit(state,uid,death=False):
    found=location(state,uid)
    if not found:return
    seat,row,c=found
    if death:
        # Sacrifice bypasses shields; the same death batch and trigger pipeline applies.
        c['sacrificed']=True
        return
    state['players'][seat]['rows'][row].remove(c);detach_targets(state,c);reset(c)
    state['players'][c['owner']]['hand'].append(c)


def execute(state,seat,item,rng=None):
    kind=item['kind'];p=state['players'][seat];targets=item.get('targets',[]);n=item.get('amount',0)
    if kind.startswith('expedition_'):expedition.execute(state,seat,item)
    elif kind=='draw':draw(p,n)
    elif kind=='cycle':
        if draw(p,item['draw']):state['work'].insert(0,op('discard_choice',seat=seat,count=item['drop']))
    elif kind=='discard_hand':
        for uid in targets:
            c=next((c for c in p['hand'] if c['id']==uid),None)
            if c:p['hand'].remove(c);discard(state,c)
    elif kind=='damage':
        hit=damage(state,seat,targets,n,item.get('damage_source'))
        if item.get('hunter_followup') and hit:
            found=location(state,hit[0])
            if found:
                side,row,c=found
                detail=row_power_details(state,side,row)[state['players'][side]['rows'][row].index(c)]
                if detail['raw']<=0:
                    state['work'].insert(0,op('hunter_followup',seat=seat,source=item['damage_source']))
    elif kind in ('boost','heal','shield','strip_boost','strip_shield','seal','unseal'):
        for uid in targets:
            found=location(state,uid)
            if not found:continue
            side,row,c=found
            if kind=='boost':
                key='uncapped_boost' if item.get('uncapped') else 'boost'
                c[key]=c.get(key,0)+n
            if kind=='heal':c['damage']=max(0,c.get('damage',0)-n)
            if kind=='shield':c['shield']=min(3,c.get('shield',0)+n)
            if kind=='strip_boost':c['boost']=max(0,c.get('boost',0)-n)
            if kind=='strip_shield':c['shield']=0
            if kind=='seal':c['sealed']=True
            if kind=='unseal':
                c.pop('sealed',None)
                for owner in state['players']:
                    for spell in owner['spells']:
                        if spell['card']=='c120' and uid in spell.get('targets',[]):spell['targets'].remove(uid)
    elif kind=='devour':
        source=location(state,item['source'])
        victims=[location(state,uid) for uid in targets]
        if source and source[0]==seat and len(set(targets))==2 and all(v and normal(v[2]) and v[2]['id']!=item['source'] for v in victims):
            total=3*sum(side==seat for side,_,_ in victims)
            execute(state,seat,op('boost',targets=[item['source']],amount=total,uncapped=True))
            for uid in targets:remove_unit(state,uid,True)
            state['events'].append(f"{definition(source[2])['name']} 吞噬两名单位，战力＋{total}")
    elif kind=='bounce':remove_unit(state,targets[0])
    elif kind=='sacrifice':remove_unit(state,targets[0],True)
    elif kind in ('destroy_spell','bounce_spell'):
        c=entity(state,targets[0])
        if c:
            owner=state['players'][c['owner']]
            if c in owner['spells']:
                owner['spells'].remove(c);reset(c)
                if kind=='destroy_spell':discard(state,c)
                else:owner['hand'].append(c)
    elif kind in ('mark','mark_row'):
        c=entity(state,item['source'])
        if c:
            if kind=='mark':c['targets']=targets
            else:c['row']=item['row']
    elif kind=='move':
        found=location(state,targets[0])
        if found:
            side,old,c=found;row=item['row'];owner=state['players'][side]
            if old!=row and len(owner['rows'][row])<ROW_CAPACITY:
                owner['rows'][old].remove(c);owner['rows'][row].append(c)
                if state['action_id'] not in p['moved_actions']:p['moved_actions'].append(state['action_id'])
                record_entry(state,side,c,row)
                state['move_count']=state.get('move_count',0)+1
                if c['card']=='c042' and not sealed(state,c):state['work'].insert(0,op('boost',seat=side,targets=[c['id']],amount=2,cue_source=c['card']))
                if c['card']=='c043' and not sealed(state,c) and c.get('move_draw_round')!=state['round']:
                    c['move_draw_round']=state['round'];state['work'].insert(0,op('draw',seat=side,amount=2,cue_source=c['card']))
                if c['card']=='c050' and not sealed(state,c) and c.get('bounce_round')!=state['round']:
                    c['bounce_round']=state['round'];state['work'].insert(0,op('bounce',seat=side,targets=[c['id']],cue_source=c['card']))
                if n:state['work'].insert(0,op('boost',seat=seat,targets=[c['id']],amount=n))
    elif kind in ('summon','revive'):
        zone=p['deck'] if kind=='summon' else p['discard']
        c=next((c for c in zone if c['id']==targets[0]),None)
        if c and len(p['rows'][item['row']])<ROW_CAPACITY:
            zone.remove(c);reset(c)
            if kind=='revive':c['revived_round']=state['round']
            elif c['id'] not in p['summoned']:p['summoned'].append(c['id'])
            put(state,seat,c,item['row'])
            if kind=='revive' and item.get('deploy'):state['work'].insert(0,op('deploy',seat=seat,source=c['id']))
    elif kind=='recover':
        c=next((c for c in p['discard'] if c['id']==targets[0]),None)
        if c:
            p['discard'].remove(c);reset(c);p['hand'].append(c)
            if item.get('source'):entity(state,item['source'])['resource_used']=True
            if definition(c)['type']=='special':c['recovered']=True
    elif kind=='exchange':
        source=entity(state,item['source'])
        a=next((c for c in p['hand'] if c['id']==targets[0]),None)
        b=next((c for c in p['discard'] if c['id']==targets[1]),None)
        if a and b and not source.get('exchange_used') and not definition(a)['hero'] and not definition(b)['hero']:
            p['hand'].remove(a);p['discard'].remove(b)
            discard(state,a);reset(b);p['hand'].append(b);source['exchange_used']=True
    elif kind=='recast':
        c=next((c for c in p['discard'] if c['id']==targets[0]),None)
        if c and not c.get('ritualist_used') and definition(c)['type']=='special' and not definition(c)['persistent'] and menu(state,seat,c):
            c['ritualist_used']=True
            p['discard'].remove(c);reset(c);p['resolving'].append(c)
            p['instant_count']+=1;p['spell_count']+=1
            state['events'].append(f"从弃牌区施放 {definition(c)['name']}")
            state['work'][0:0]=[op('spell_menu',seat=seat,source=c['id']),op('finish_spell',seat=seat,source=c['id'])]
    elif kind=='purge_spells':
        spells=[c for owner in state['players'] for c in owner['spells']]
        for c in spells:execute(state,seat,op('destroy_spell',targets=[c['id']]))
        execute(state,seat,op('boost',targets=[item['source']],amount=2*len(spells),uncapped=True))
    elif kind in ('persistent_boost','enemy_spell_boost'):
        for uid in targets:
            found=location(state,uid)
            if found and found[0]==seat and not sealed(state,found[2]):
                execute(state,seat,op('boost',targets=[uid],amount=3 if kind=='persistent_boost' else 2,uncapped=True))
    elif kind=='bottom':
        zone=p[item['zone']];c=next((c for c in zone if c['id']==targets[0]),None)
        if c:zone.remove(c);p['deck'].insert(0,c)
    elif kind=='return_deck':
        c=next((c for c in p['discard'] if c['id']==targets[0]),None)
        if c:
            p['discard'].remove(c);reset(c);p['deck'].append(c)
            (rng or random.Random()).shuffle(p['deck'])
    elif kind=='recycle':
        c=next((c for c in p['discard'] if c['id']==targets[0]),None)
        if c:
            p['discard'].remove(c);reset(c);p['deck'].append(c)
            state['work'].insert(0,op('recycle_choice',seat=seat,count=item['count']-1))
    elif kind=='top':
        top=p['deck'][-2:];p['deck']=p['deck'][:-len(top)]
        selected=next(c for c in top if c['id']==targets[0])
        p['hand'].append(selected)
        for c in top:
            if c is not selected:discard(state,c)


def queue_menu(state,seat,options,title='选择目标'):
    if options:state['work'].insert(0,op('choice',seat=seat,options=options,title=title))


def deployment(state,seat,c):
    if not location(state,c['id']) or sealed(state,c):return
    p=state['players'][seat];cid=c['card'];row=location(state,c['id'])[1]
    automatic=[]
    if 'spy' in definition(c)['abilities'] and not c.get('spy_used'):
        c['spy_used']=True;automatic=[op('draw',amount=2)]
    if cid=='c002':automatic=[op('boost',targets=[c['id']],amount=2)]
    if cid=='c056' and p['spell_count']>p['instant_count']:automatic=[op('draw',amount=p['spell_count']-p['instant_count'])]
    if cid=='c006' and len(p['rows'][row])>=3:automatic=[op('draw',amount=1)]
    if cid=='c009':automatic=[op('cycle',draw=2,drop=1)]
    if cid=='c068':automatic=[op('boost',targets=[u['id'] for u in units(state,seat) if normal(u)],amount=1,uncapped=True)]
    if cid=='c026' and len(units(state,seat))==1 and not c.get('resource_used'):
        c['resource_used']=True;automatic=[op('draw',amount=1)]
    if cid=='c078' and len(units(state,seat))>=len(units(state,1-seat)):automatic=[op('boost',targets=[c['id']],amount=2)]
    if cid=='c081' and p.get('discarded_this_round'):automatic=[op('boost',targets=[c['id']],amount=2)]
    if cid=='c082' and p['instant_count']>0:automatic=[op('boost',targets=[c['id']],amount=4)]
    if cid=='c089' and p.get('discarded_this_round') and not c.get('young_draw_used'):
        c['young_draw_used']=True;automatic=[op('draw',amount=2)]
    if cid=='c095':automatic=[op('purge_spells',source=c['id'])]
    for item in automatic:item.update(seat=seat,cue_source=cid)
    if automatic:state['work'][0:0]=automatic;return
    options=menu(state,seat,c)
    if cid in ('c061','c062','c063'):
        if options:state['work'].insert(0,op('repeat_menu',seat=seat,source=c['id'],exclude=[]))
    if cid in ('c048','c050','c052','c055','c069','c077','c087','c104','c107','c045','c046','c047','c061','c062','c063','c064','c065','c066') and options:options.append(option('跳过',[op('cancel_repeat')] if 'muster' in definition(c)['abilities'] else []))
    queue_menu(state,seat,options)


def drain(state,rng=None):
    rng=rng or random.Random()
    while state['work'] and not state['pending']:
        item=state['work'].pop(0);seat=item.get('seat',state['actor']);kind=item['kind'];p=state['players'][seat]
        changes_board=kind not in ('choice','deploy','cancel_repeat','spell_menu','repeat_menu','second_move','recover_choice','bottom_hand_choice','discard_choice','hunter_followup','death_boost','end_triggers')
        before=board_snapshot(state) if changes_board else None;hand_before=len(p['hand'])
        source=entity(state,item.get('source') or item.get('damage_source'))
        cue_source=item.get('cue_source') or (source['card'] if source else None)
        if kind=='choice':
            options=item['options']
            for index,o in enumerate(options):
                o['token']=str(index)
                targets=dict.fromkeys(uid for effect in o['ops'] for uid in effect.get('targets',[]))
                hints=[]
                for uid in targets:
                    found=location(state,uid)
                    if found:
                        side,row,c=found;slot=state['players'][side]['rows'][row].index(c)
                        power=row_power_details(state,side,row)[slot]['power']
                        hints.append(f"{'己方' if side==seat else '敌方'}{['近战','远程','攻城'][row]}{slot+1}位 · 战力{power}")
                o['hint']=' / '.join(hints)
            state['pending']=dict(actor=seat,kind='v3',title=item['title'],options=options,continuation='finish_action')
        elif kind=='deploy':deployment(state,seat,entity(state,item['source']))
        elif kind=='cancel_repeat':state['work']=[x for x in state['work'] if x['kind']!='repeat_menu']
        elif kind=='spell_menu':
            c=entity(state,item['source'])
            options=menu(state,seat,c)
            if c['card']=='c093' and options:p['prayer_round']=state['round']
            queue_menu(state,seat,options,definition(c)['name']+'：选择目标')
        elif kind=='repeat_menu':
            c=entity(state,item['source']);options=menu(state,seat,c)
            if options:queue_menu(state,seat,options+[option('结束召集',[])],'继续召集（剩余1张）')
        elif kind=='second_move':
            options=[o for o in menu(state,seat,dict(card='c059',id='leader')) if o['card']['id']!=item['exclude']]
            queue_menu(state,seat,options+[option('结束转阵',[])],'可再移动一名不同的单位')
        elif kind=='recycle_choice':
            if item['count'] and p['discard']:
                queue_menu(state,seat,target_options(p['discard'],'recycle',count=item['count']),'选择洗回牌库的牌')
            else:rng.shuffle(p['deck']);draw(p,1)
        elif kind=='recover_choice':
            queue_menu(state,seat,target_options(p['discard'],'recover'),'选择一张弃牌加入手牌')
        elif kind=='bottom_hand_choice':
            queue_menu(state,seat,target_options(p['hand'],'bottom',zone='hand'),'选择一张手牌放到牌库底')
        elif kind=='discard_choice':
            count=min(item['count'],len(p['hand']))
            if count:queue_menu(state,seat,[option('弃置 '+label(list(g)),[op('discard_hand',targets=[c['id'] for c in g])],g[0]) for g in combinations(p['hand'],count)],'选择弃置的手牌')
        elif kind=='hunter_followup':
            options=menu(state,seat,entity(state,item['source']))
            for choice in options:
                for effect in choice['ops']:effect.pop('hunter_followup',None)
            if options:queue_menu(state,seat,options+[option('放弃追击',[])],'灰羽猎手：可追加一次追击')
        elif kind=='death_boost':queue_menu(state,seat,target_options(units(state,seat),'boost',3),'阵亡：选择强化目标')
        elif kind=='finish_spell':
            c=entity(state,item['source']);p['resolving'].remove(c);discard(state,c)
            for spell in list(p['spells']):
                if spell['card']=='c094' and spell.get('healed_round',0)<2:
                    candidates=[(d['power'],c['entered'],c['id']) for row in range(3) for c,d in zip(p['rows'][row],row_power_details(state,seat,row))]
                    if candidates:
                        execute(state,seat,op('boost',targets=[min(candidates)[2]],amount=3))
                        spell['healed_round']=spell.get('healed_round',0)+1
        elif kind=='end_triggers':
            state['work'].extend(expedition.end_play(state,seat))
            for side in (seat,1-seat):
                for spell in list(state['players'][side]['spells']):
                    if spell['card']=='c114' and spell.get('ticks',0)<3 and not state['players'][1-side]['passed']:
                        if state.get('played_card') and side!=seat:
                            targets=[uid for uid in spell.get('targets',[]) if location(state,uid)]
                            if targets:
                                spell['ticks']=spell.get('ticks',0)+1
                                state['work'].append(op('damage',seat=side,targets=targets,amount=2,cue_source=spell['card']))
                    if spell['card']=='c014' and spell.get('entry_draws',0)<2:
                        candidates=[x for x in state['entered_action'] if x['seat']==side and x['row']==spell.get('row')]
                        count=min(2-spell.get('entry_draws',0),len(candidates))
                        if count:
                            spell['entry_draws']=spell.get('entry_draws',0)+count
                            state['work'].append(op('draw',seat=side,amount=count,cue_source=spell['card']))
                    if spell['card']=='c054' and spell.get('trap_used',0)<3:
                        candidates=[x for x in state['entered_action'] if x['seat']==1-side and x['row']==spell.get('row') and location(state,x['id']) and location(state,x['id'])[:2]==(1-side,x['row'])]
                        if candidates:
                            spell['trap_used']=spell.get('trap_used',0)+1
                            state['work'].append(op('damage',seat=side,targets=[candidates[0]['id']],amount=2,cue_source=spell['card']))
        else:execute(state,seat,item,rng)
        settle(state)
        if before is not None:record_changes(state,before,kind,seat,cue_source,hand_before,item.get('targets',[]))


def start_action(state,seat):
    state['actor']=seat;state['action_id']+=1;state['entered_action']=[];state['events']=[];state['played_card']=None
    state['dead_before']=[p['normal_deaths'] for p in state['players']]


def can_play(state,seat,c,row):
    d=definition(c);p=state['players'][seat]
    if type(row) is not int:return False
    if d['type']=='unit':
        if c['card']=='c076' and sum(normal(u) for u in units(state,seat)+units(state,1-seat))<2:return False
        destination=1-seat if 'spy' in d['abilities'] else seat
        return row in d['rows'] and len(state['players'][destination]['rows'][row])<ROW_CAPACITY
    if d['type']!='special' or row!=-1:return False
    return (not d['persistent'] or len(p['spells'])<SPELL_CAPACITY) and bool(menu(state,seat,c))


def play_card(state,seat,c,row,rng):
    d=definition(c);p=state['players'][seat]
    if not can_play(state,seat,c,row):raise ValueError('无法出牌：战列已满、术位已满或没有合法目标')
    before=board_snapshot(state)
    start_action(state,seat);state['played_card']=c['id'];p['hand'].remove(c)
    if d['type']=='unit':
        put(state,1-seat if 'spy' in d['abilities'] else seat,c,row)
        state['work']=[op('deploy',seat=seat,source=c['id']),op('end_triggers',seat=seat)]
    else:
        p['spell_count']+=1
        if d['persistent']:p['spells'].append(c)
        else:p['instant_count']+=1;p['resolving'].append(c)
        state['work']=[op('enemy_spell_boost',seat=1-seat,targets=[u['id'] for u in units(state,1-seat) if u['card']=='c049' and not sealed(state,u)]),
                       op('spell_menu',seat=seat,source=c['id'])]
        if not d['persistent']:state['work'].append(op('finish_spell',seat=seat,source=c['id']))
        else:state['work'].append(op('persistent_boost',seat=seat,targets=[u['id'] for u in units(state,seat) if u['card']=='c088' and not sealed(state,u)]))
        state['work'].append(op('end_triggers',seat=seat))
    settle(state);record_changes(state,before,'play',seat,c['card']);drain(state,rng)


def choose(state,seat,token,rng):
    pending=state['pending']
    if not pending or pending['actor']!=seat:raise ValueError('当前无需选择')
    selected=next((o for o in pending['options'] if o['token']==token),None)
    if selected is None:raise ValueError('选择已失效')
    state['pending']=None
    state['work'][0:0]=[dict(item,seat=seat) for item in selected['ops']]
    drain(state,rng)


def can_lead(state,seat):
    p=state['players'][seat]
    return bool(p['leader']) and not p['leader_used'] and bool(menu(state,seat,dict(card=p['leader'],id='leader')))


def leader(state,seat,rng):
    p=state['players'][seat]
    if not can_lead(state,seat):raise ValueError('领袖已使用或没有合法目标')
    options=menu(state,seat,dict(card=p['leader'],id='leader'))
    start_action(state,seat);p['leader_used']=True
    # Leaders are not card entities. Their own once-per-match flag is sufficient.
    for o in options:
        if p['leader']=='c059':o['ops'].append(op('second_move',exclude=o['card']['id']))
        for item in o['ops']:
            if item.get('source')=='leader':item['source']=None
    state['work']=[op('choice',seat=seat,options=options,title='领袖：选择目标'),op('end_triggers',seat=seat)]
    drain(state,rng)
