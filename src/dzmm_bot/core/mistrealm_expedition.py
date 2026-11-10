"""Server-authoritative, resumable 63-node solo expedition."""
from copy import deepcopy
from uuid import uuid4

from . import mistrealm_v3_state as game
from .mistrealm_v3_ai import pick_move
from .mistrealm_v3_cards import CARDS as BASE_CARDS, STARTER_DECKS
from .mistrealm_expedition_cards import CARDS, FACTIONS

CATALOGUE = {**BASE_CARDS, **CARDS}
ROUTES = ('normal', 'elite', 'shop', 'event', 'upgrade')
NAMES = dict(normal='普通战斗', elite='精英战斗', shop='商店', event='随机事件', upgrade='强化', boss='英雄Boss')


def pool(faction=None):
    return [cid for cid,d in CATALOGUE.items() if d['type']!='leader' and (cid in BASE_CARDS or d['faction']==faction)]


def offers(rng, faction=None, *, boss=False):
    cards=pool(faction)
    units=[cid for cid in cards if CATALOGUE[cid]['type']=='unit' and not CATALOGUE[cid]['hero']]
    spells=[cid for cid in cards if CATALOGUE[cid]['type']=='special']
    if boss:
        heroes=[cid for cid in cards if CATALOGUE[cid]['hero']]
        return rng.sample(heroes,1)+rng.sample(units,1)+rng.sample(spells,1)
    return rng.sample(units,2)+rng.sample(spells,1)


def new_run(rng):
    bosses={f:rng.sample([cid for cid,d in CARDS.items() if d['faction']==f and d['hero']],3) for f in FACTIONS}
    return dict(id=str(uuid4()),version=0,phase='draft',deck=[],gold=20,chapter=0,stage=0,node=0,
                completed=0,last_node=None,bosses=bosses,offers=offers(rng),battle=None,
                last_result=None,battle_serial=0,log=[])


def faction(run):
    return list(FACTIONS)[run['chapter']]


def add_card(run,cid):
    run['deck'].append(dict(id=str(uuid4()),card=cid,expedition_upgrade=0))


def route(run,rng):
    run['phase']='route'
    choices=[k for k in ROUTES if k!='shop' or (run['completed']>0 and run['last_node']!='shop')]
    run['offers']=['boss'] if run['node']==6 else rng.sample(choices,3)


def advance(run,rng):
    run['completed']+=1;run['node']+=1
    if run['node']==7:
        run['node']=0;run['stage']+=1
    if run['stage']==3:
        run['stage']=0;run['chapter']+=1
    if run['chapter']==3:
        run.update(phase='finished',offers=[])
    else:route(run,rng)


def begin_battle(run,uid,now_ms,rng,kind,step):
    run.update(phase='battle',offers=[],last_result=None,battle_kind=kind,battle_step=step)
    run['battle_serial']=run.get('battle_serial',0)+1
    run['battle']=new_battle(run,uid,now_ms,rng,kind)


def finish_reward(run,rng):
    run['battle']=None
    if run.pop('reward_next','advance')=='route':route(run,rng)
    else:advance(run,rng)


def new_battle(run, uid, now_ms, rng, kind):
    # Constructed deck validation remains strict. Only this server-owned adapter
    # replaces the validated starter with the expedition's persisted entities.
    s=game.new_state(uid,STARTER_DECKS[0],now_ms)
    s['players'][1]=game._player('expedition-enemy',STARTER_DECKS[0])
    f=faction(run);units=[cid for cid,d in CARDS.items() if d['faction']==f and d['type']=='unit' and not d['hero']]
    spells=[cid for cid,d in CARDS.items() if d['faction']==f and d['type']=='special']
    enemy=rng.sample(units,6)+rng.sample(spells,2)
    boss=run['bosses'][f][run['stage']] if kind=='boss' else None
    if boss:enemy.append(boss)
    power=run['chapter']+run['stage']//2+(kind=='elite')
    decks=[deepcopy(run['deck']),[dict(id=f'enemy:{i}',card=cid,expedition_upgrade=power) for i,cid in enumerate(enemy)]]
    for seat,p in enumerate(s['players']):
        p.update(faction='neutral' if seat==0 else f,leader=None,leader_used=True,leader_disabled=True,locked=True,mulligan_done=True)
        p['selection']={};p['deck']=decks[seat]
        for c in p['deck']:c['owner']=seat
        rng.shuffle(p['deck'])
        if seat==1 and boss:
            hero=next(c for c in p['deck'] if c['card']==boss);p['deck'].remove(hero);p['deck'].append(hero)
        game._draw(p,5)
    s.update(mode='expedition',phase='playing',round=1,lives=[1,1],first=0,turn=0,
             move_count=0,deadline_ms=None,events=['远征战斗：单局定胜负，双方无领袖。'])
    game._log(s,'round_start',NAMES[kind]+' · '+(CARDS[boss]['name'] if boss else FACTIONS[f]))
    return s


def drive(s,now_ms,rng):
    for _ in range(120):
        if s['phase']=='finished':break
        actor=s['pending']['actor'] if s['pending'] else s['turn']
        if actor==0:break
        move=pick_move(s,1)
        if not move:raise ValueError('敌方没有可执行行动')
        s=game.apply_action(s,1,move['action'],move['payload'],now_ms,rng)
    else:raise ValueError('本次效果链过长，请重新尝试')
    s['deadline_ms']=None
    return s


def battle_result(run,rng):
    s=run['battle']
    if s['phase']!='finished':return
    won=s['winner']==0
    kind=run.get('battle_kind',run['last_node'])
    run['last_result']=dict(won=won,tied=s['winner'] is None,scores=[sum(game.score_rows(s,i)) for i in (0,1)])
    run['log'].append(dict(chapter=run['chapter'],stage=run['stage'],node=run['node'],kind=kind,step=run.get('battle_step','route'),**run['last_result']))
    if not won:run.update(phase='lost',offers=[]);return
    run['gold']+=dict(normal=10,elite=18,boss=25)[kind]
    run.update(phase='reward',offers=offers(rng,faction(run),boss=kind=='boss'),
               reward_next='route' if run.get('battle_step')=='wave' else 'advance')


def _index(payload, values):
    index=payload.get('index')
    if set(payload)!={'index'} or type(index) is not int or not 0<=index<len(values):raise ValueError('请选择当前显示的选项')
    return index


def act(run,uid,action,payload,now_ms,rng):
    r=deepcopy(run);phase=r['phase']
    # Older saves offered two randomly ordered events; keep the first result.
    if phase=='event':r['offers']=r['offers'][:1]
    if action=='restart':
        if payload:raise ValueError('无效参数')
        fresh=new_run(rng);fresh['version']=r['version']+1;return fresh
    if action=='battle':
        if phase!='battle' or set(payload)!={'action','payload'} or payload['action'] not in ('play','pass','choose','concede'):raise ValueError('当前不可执行此战斗操作')
        r['battle']=drive(game.apply_action(r['battle'],0,payload['action'],payload['payload'],now_ms,rng),now_ms,rng)
        battle_result(r,rng)
    elif action=='choose':
        if phase not in ('draft','route','reward','event'):raise ValueError('当前无需选择路线或卡牌')
        choice=r['offers'][_index(payload,r['offers'])]
        if phase in ('draft','reward'):
            add_card(r,choice)
            if phase=='reward':finish_reward(r,rng)
            elif len(r['deck'])==5:route(r,rng)
            else:r['offers']=offers(rng)
        elif phase=='route':
            r['last_node']=choice;r['offers']=[];r['last_result']=None;r['upgrade_bought']=False
            if choice in ('normal','elite','boss'):
                begin_battle(r,uid,now_ms,rng,choice,'route')
            elif choice=='shop':r.update(phase='shop',offers=offers(rng,faction(r)))
            elif choice=='upgrade':r['phase']='upgrade'
            else:r.update(phase='event',offers=rng.sample(['gold','cache','training'],1))
        else:
            if choice=='gold':r['gold']+=15;advance(r,rng)
            elif choice=='cache':r.update(phase='reward',offers=offers(rng,faction(r)),reward_next='advance')
            else:r['phase']='upgrade'
    elif action=='buy':
        if phase!='shop':raise ValueError('当前不在商店')
        index=_index(payload,r['offers'])
        if r['gold']<15:raise ValueError('金币不足，需要15金币')
        add_card(r,r['offers'].pop(index));r['gold']-=15
    elif action in ('upgrade','sell'):
        if phase not in (('shop',) if action=='sell' else ('shop','upgrade')) or set(payload)!={'card'}:raise ValueError('当前不可修改牌组')
        c=next((c for c in r['deck'] if c['id']==payload['card']),None)
        if not c:raise ValueError('牌组中没有这张卡')
        if action=='sell':
            if len(r['deck'])<=5:raise ValueError('出售后牌组至少保留5张')
            r['deck'].remove(c);r['gold']+=5
        else:
            if CATALOGUE[c['card']]['type']!='unit':raise ValueError('请选择单位牌强化')
            if r.get('upgrade_bought'):raise ValueError('本节点已购买过强化')
            if r['gold']<10:raise ValueError('金币不足，需要10金币')
            c['expedition_upgrade']+=2;r['gold']-=10;r['upgrade_bought']=True
            if phase=='upgrade':advance(r,rng)
    elif action=='skip':
        if phase!='reward' or payload:raise ValueError('当前不可跳过选卡')
        finish_reward(r,rng)
    elif action=='leave':
        if phase not in ('shop','upgrade') or payload:raise ValueError('当前不可跳过')
        advance(r,rng)
    else:raise ValueError('无效远征操作')
    r['version']+=1
    return r


def project(run):
    if run is None:return None
    result={k:deepcopy(run[k]) for k in ('id','version','phase','deck','gold','chapter','stage','node','completed','offers','last_result','last_node','log')}
    if run['phase']=='event':result['offers']=result['offers'][:1]
    result['upgrade_bought']=run.get('upgrade_bought',False)
    result['battle_serial']=run.get('battle_serial',0)
    result['faction']=faction(run) if run['chapter']<3 else None
    result['boss']=run['bosses'][faction(run)][run['stage']] if run['chapter']<3 else None
    result['battle']=game.project(run['battle'],0) if run['battle'] else None
    return result
