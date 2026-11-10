from copy import deepcopy
import json
from pathlib import Path
from random import Random

import pytest

from dzmm_bot.core import mistrealm_expedition as x, mistrealm_v3_effects as fx
from dzmm_bot.core.mistrealm_v3_scoring import definition
from dzmm_bot.core.mistrealm_v3_cards import validate_deck, STARTER_DECKS
from tests.core.test_mistrealm_v3 import empty,add,play,finish
from tests.core.test_mistrealm_v3_revision2 import strength


def drafted(seed=0):
    rng=Random(seed);r=x.new_run(rng)
    for _ in range(5):r=x.act(r,'a','choose',{'index':0},0,rng)
    return r


def test_draft_pools_and_pvp_isolation():
    r=drafted()
    assert r['phase']=='route' and r['battle'] is None and len(r['deck'])==5
    assert not set(x.pool()) & set(x.CARDS)
    for f in x.FACTIONS:
        faction_cards=[d for d in x.CARDS.values() if d['faction']==f]
        assert len(faction_cards)==20
        assert sum(d['type']=='unit' and not d['hero'] for d in faction_cards)==12
        assert sum(d['hero'] for d in faction_cards)==4
        assert sum(d['type']=='special' and not d['persistent'] for d in faction_cards)==1
        assert sum(d['persistent'] for d in faction_cards)==1
        assert sum(d['type']=='leader' for d in faction_cards)==2
        mixed=x.pool(f)
        assert len({x.CATALOGUE[c]['faction'] for c in mixed})==7
        assert all(x.CATALOGUE[c]['type']!='leader' for c in mixed)
        assert len(r['bosses'][f])==len(set(r['bosses'][f]))==3
    deck=deepcopy(STARTER_DECKS[0]);deck['counts']['xb01']=1
    with pytest.raises(ValueError,match='未知卡牌'):validate_deck(deck['faction'],deck['leader'],deck['counts'])
    assert len(x.BASE_CARDS)==120 and len(x.CARDS)==60
    assert all((Path('gamefy/mistrealm/publish/v3')/d['art']).is_file() for d in x.CARDS.values())


def test_shop_never_first_or_consecutive_and_63_nodes_end():
    r=drafted();rng=Random(7);seen=[]
    for _ in range(63):
        x.route(r,rng)
        if r['completed']==0 or r['last_node']=='shop':assert 'shop' not in r['offers']
        if r['node']==6:
            assert r['offers']==['boss'];seen.append(r['bosses'][x.faction(r)][r['stage']])
        else:assert len(r['offers'])==len(set(r['offers']))==3
        r['last_node']='shop' if r['completed']%2 else 'normal'
        x.advance(r,rng)
    assert r['phase']=='finished' and r['completed']==63
    assert len(seen)==len(set(seen))==9


def test_battles_start_with_five_cards_no_leader_and_restore_entities():
    r=drafted();r['deck'][0]['expedition_upgrade']=4
    x.add_card(r,'xb01');original=deepcopy(r['deck'])
    s=x.new_battle(r,'a',0,Random(1),'boss')
    assert s['lives']==[1,1]
    assert s['players'][0]['leader'] is None and s['players'][1]['leader'] is None
    assert not fx.can_lead(s,0)
    assert len(s['players'][0]['hand'])==len(s['players'][1]['hand'])==5
    assert any(c['card']==r['bosses'][x.faction(r)][0] for c in s['players'][1]['hand'])
    c=s['players'][0]['hand'].pop();fx.discard(s,c)
    c['damage']=99
    resumed=x.new_battle(r,'a',2,Random(3),'normal')
    entities=resumed['players'][0]['hand']+resumed['players'][0]['deck']
    assert {c['id'] for c in entities}=={c['id'] for c in original}
    assert all('damage' not in c and 'revived_round' not in c for c in entities)
    assert r['deck']==original
    assert next(c for c in entities if c['id']==original[0]['id'])['expedition_upgrade']==4
    view=x.game.project(resumed,0)
    assert 'hand' not in view['players'][1] and 'deck' not in view['players'][1]


def test_reward_cannot_be_claimed_twice_and_bad_actions_are_atomic():
    r=drafted();r.update(phase='reward',offers=['xb01','c001','c101'])
    result=x.act(r,'a','choose',{'index':0},0,Random(0))
    assert result['completed']==1 and len(result['deck'])==6
    assert len(r['deck'])==5 and r['completed']==0
    before=deepcopy(result)
    with pytest.raises(ValueError):x.act(result,'a','choose',{'index':999},0,Random(0))
    assert result==before
    with pytest.raises(ValueError):x.act(result,'a','buy',{'index':0},0,Random(0))


def test_shop_and_upgrade_preserve_card_identity_and_gold():
    r=drafted();r.update(phase='shop',offers=['xb01','xv01','xa01'],gold=30)
    r=x.act(r,'a','buy',{'index':0},0,Random(0))
    assert r['gold']==15 and len(r['deck'])==6 and 'xb01' not in r['offers']
    uid=r['deck'][-1]['id'];r=x.act(r,'a','sell',{'card':uid},0,Random(0))
    assert r['gold']==20 and len(r['deck'])==5
    with pytest.raises(ValueError):x.act(r,'a','sell',{'card':r['deck'][0]['id']},0,Random(0))
    r.update(phase='upgrade');x.add_card(r,'xb01');uid=r['deck'][-1]['id']
    r=x.act(r,'a','upgrade',{'card':uid},0,Random(0))
    c=next(c for c in r['deck'] if c['id']==uid)
    assert definition(c)['power']==5 and x.CARDS['xb01']['power']==3
    assert r['gold']==10 and r['phase']=='route'


@pytest.mark.parametrize('cid',[cid for cid,d in x.CARDS.items() if d['type']!='leader'])
def test_all_new_cards_have_legal_resolving_effects(cid):
    s=empty();s['mode']='expedition'
    # Give every targeting/revival/condition archetype a meaningful board.
    for side in (0,1):
        for row in (0,1,2):add(s,'c101',seat=side,zone='rows',row=row,damage=1)
        for _ in range(4):add(s,'c101',seat=side,zone='deck')
        add(s,'c043',seat=side,zone='discard')
        add(s,'c118',seat=side,zone='spells',targets=[])
    c=add(s,cid);d=x.CARDS[cid];row=d['rows'][0] if d['rows'] else -1
    assert fx.can_play(s,0,c,row)
    initial={c['id'] for p in s['players'] for zone in ('hand','deck','discard','spells') for c in p[zone]}|{c['id'] for p in s['players'] for lane in p['rows'] for c in lane}
    result=finish(play(s,c,row))
    assert result['pending'] is None
    entities=[c for p in result['players'] for zone in ('hand','deck','discard','spells','resolving') for c in p[zone]]+[c for p in result['players'] for lane in p['rows'] for c in lane]
    assert len(entities)==len(initial) and {c['id'] for c in entities}==initial
    json.dumps(x.game.project(result,0))


def test_drain_does_not_gain_overkill_and_death_draw_is_once_after_revive():
    s=empty();a=add(s,'xv01',zone='rows');b=add(s,'c101',seat=1,zone='rows',damage=1)
    before=strength(s,b)
    fx.execute(s,0,fx.op('expedition_drain',source=a['id'],targets=[b['id']],amount=99))
    assert strength(s,a)==2+before
    s=empty();c=add(s,'xb06',zone='rows');add(s,'c101',zone='deck');add(s,'c101',zone='deck')
    fx.damage(s,1,[c['id']],10);fx.settle(s);fx.drain(s,Random(1))
    assert len(s['players'][0]['hand'])==1
    fx.execute(s,0,fx.op('revive',targets=[c['id']],row=0));fx.damage(s,1,[c['id']],10);fx.settle(s);fx.drain(s,Random(1))
    assert len(s['players'][0]['hand'])==1


def test_persistent_spell_stops_after_three_own_plays():
    s=empty();friend=add(s,'c101',zone='rows');spell=add(s,'xa09')
    s=finish(play(s,spell));assert fx.entity(s,friend['id'])['boost']==1
    for i in range(4):
        s['turn']=0;c=add(s,'c103');s=finish(play(s,c,1))
    assert fx.entity(s,friend['id'])['boost']==3
    assert fx.entity(s,spell['id'])['ticks']==3


def test_auto_opponent_completes_a_single_round_and_no_leader_action():
    r=drafted();rng=Random(4);r.update(phase='battle',last_node='normal')
    r['battle']=x.new_battle(r,'a',0,rng,'normal')
    for _ in range(80):
        if r['phase']!='battle':break
        s=r['battle'];moves=x.game.legal_moves(s,0)
        assert not any(m['action']=='leader' for m in moves)
        move=next((m for m in moves if m['action']=='choose'),None) or next((m for m in moves if m['action']=='play'),None) or dict(action='pass',payload={})
        r=x.act(r,'a','battle',move,0,rng)
    assert r['phase'] in ('lost','reward')
    assert r['battle']['round']==1
    assert r['battle']['phase']=='finished'


def test_card_choices_are_two_units_one_spell_and_heroes_only_after_boss():
    rng=Random(17)
    for f in (None,*x.FACTIONS):
        for _ in range(100):
            ordinary=x.offers(rng,f)
            assert sum(x.CATALOGUE[c]['type']=='unit' for c in ordinary)==2
            assert sum(x.CATALOGUE[c]['type']=='special' for c in ordinary)==1
            assert not any(x.CATALOGUE[c]['hero'] for c in ordinary)
            boss=x.offers(rng,f,boss=True)
            assert sum(x.CATALOGUE[c]['hero'] for c in boss)==1
            assert sum(x.CATALOGUE[c]['type']=='unit' and not x.CATALOGUE[c]['hero'] for c in boss)==1
            assert sum(x.CATALOGUE[c]['type']=='special' for c in boss)==1
            assert len(set(boss))==3


def victory(r,rng):
    r=deepcopy(r);r['battle']['phase']='finished';r['battle']['winner']=0
    x.battle_result(r,rng)
    return r


def claim(r,rng):
    return x.act(r,'a','choose',{'index':0},0,rng)


@pytest.mark.parametrize('kind,gold,boost',[('normal',10,0),('elite',18,1)])
def test_route_combat_reward_then_next_route(kind,gold,boost):
    rng=Random(3);r=drafted();assert r['battle'] is None
    r['offers']=[kind];r=x.act(r,'a','choose',{'index':0},0,rng)
    assert r['battle_kind']==kind and r['battle_step']=='route' and r['battle_serial']==1
    assert all(c['expedition_upgrade']==boost for c in r['battle']['players'][1]['hand'])
    r=victory(r,rng);assert r['gold']==20+gold and r['phase']=='reward'
    r=claim(r,rng)
    assert r['phase']=='route' and r['completed']==1 and r['battle'] is None
    assert len(r['log'])==1


@pytest.mark.parametrize('kind',['shop','upgrade','event'])
def test_noncombat_nodes_do_not_start_a_battle(kind):
    rng=Random(4);r=drafted();r['offers']=[kind]
    r=x.act(r,'a','choose',{'index':0},0,rng)
    assert r['phase']==kind and r['battle'] is None
    if kind=='event':
        assert len(r['offers'])==1
        r['offers']=['gold'];r=x.act(r,'a','choose',{'index':0},0,rng)
        assert r['gold']==35
    else:r=x.act(r,'a','leave',{},0,rng)
    assert r['phase']=='route' and r['battle'] is None and r['node']==1
    if kind=='shop':assert 'shop' not in r['offers']


def test_complete_63_nodes_without_forced_waves_and_nine_distinct_bosses():
    rng=Random(19);r=drafted();heroes=[]
    for _ in range(63):
        assert r['phase']=='route' and r['battle'] is None
        if r['node']==6:
            assert r['offers']==['boss'];heroes.append(r['bosses'][x.faction(r)][r['stage']])
            r=x.act(r,'a','choose',{'index':0},0,rng)
            assert r['battle_kind']=='boss'
            r=claim(victory(r,rng),rng)
        else:
            r['offers']=['upgrade'];r=x.act(r,'a','choose',{'index':0},0,rng)
            r=x.act(r,'a','leave',{},0,rng)
    assert r['phase']=='finished' and r['completed']==63
    assert len(heroes)==len(set(heroes))==9 and len(r['log'])==9
    assert all(e['step']=='route' for e in r['log'])
    assert r['gold']==20+9*25


def test_unlimited_deck_rewards_and_shop_purchases_keep_existing_entities():
    r=drafted();original=deepcopy(r['deck'])
    for _ in range(12):
        for cid in ('xb01','xb13','xb09'):x.add_card(r,cid)
    assert r['deck'][:5]==original and len(r['deck'])==41
    r.update(phase='reward',offers=['xb13'])
    r=claim(r,Random(1));assert len(r['deck'])==42
    r.update(phase='shop',offers=['xb09'],gold=20)
    r=x.act(r,'a','buy',{'index':0},0,Random(1))
    assert r['gold']==5 and len(r['deck'])==43 and r['offers']==[]
    assert r['deck'][:5]==original


def test_starting_draft_can_pick_five_spells_but_cannot_skip():
    rng=Random(2);r=x.new_run(rng)
    for _ in range(5):
        before=deepcopy(r)
        with pytest.raises(ValueError):x.act(r,'a','skip',{},0,rng)
        assert r==before
        r=x.act(r,'a','choose',{'index':2},0,rng)
    assert len(r['deck'])==5 and r['phase']=='route'
    assert all(x.CATALOGUE[c['card']]['type']=='special' for c in r['deck'])


def test_skip_keeps_gold_and_deck_and_cannot_repeat():
    rng=Random(7);r=drafted();x.begin_battle(r,'a',0,rng,'boss','route')
    r=victory(r,rng);original=deepcopy(r['deck'])
    r=x.act(r,'a','skip',{},0,rng)
    assert r['gold']==45 and r['deck']==original and r['completed']==1
    assert r['phase']=='route' and r['battle'] is None
    with pytest.raises(ValueError):x.act(r,'a','skip',{},0,rng)


def test_shop_upgrade_once_cost_and_sell_floor_are_authoritative():
    rng=Random(1);r=drafted();r.update(phase='shop',gold=10,offers=['xb01'])
    cid=r['deck'][0]['id'];original=deepcopy(r)
    with pytest.raises(ValueError):x.act(r,'a','buy',{'index':0},0,rng)
    with pytest.raises(ValueError):x.act(r,'a','sell',{'card':cid},0,rng)
    assert r==original
    r=x.act(r,'a','upgrade',{'card':cid},0,rng)
    assert r['gold']==0 and r['phase']=='shop' and r['deck'][0]['expedition_upgrade']==2
    r['gold']=100;before=deepcopy(r)
    with pytest.raises(ValueError,match='已购买'):x.act(r,'a','upgrade',{'card':cid},0,rng)
    assert r==before and x.project(r)['upgrade_bought']
    r=x.act(r,'a','leave',{},0,rng);r['offers']=['upgrade']
    r=x.act(r,'a','choose',{'index':0},0,rng)
    r=x.act(r,'a','upgrade',{'card':cid},0,rng)
    assert r['deck'][0]['expedition_upgrade']==4 and r['gold']==90 and r['phase']=='route'


def test_upgrade_invalid_target_or_insufficient_gold_is_atomic():
    rng=Random(2);r=drafted();x.add_card(r,'xb09');r.update(phase='upgrade',gold=9)
    for cid in (r['deck'][0]['id'],r['deck'][-1]['id'],'missing'):
        before=deepcopy(r)
        with pytest.raises(ValueError):x.act(r,'a','upgrade',{'card':cid},0,rng)
        assert r==before


def test_existing_wave_and_events_continue_without_resetting_progress():
    rng=Random(7);r=drafted();r.update(completed=9,node=2,stage=1,gold=50)
    x.begin_battle(r,'a',0,rng,'normal','wave');old_deck=deepcopy(r['deck'])
    r=victory(r,rng);r=x.act(r,'a','skip',{},0,rng)
    assert r['completed']==9 and r['node']==2 and r['gold']==60 and r['deck']==old_deck
    assert r['phase']=='route'
    r.update(phase='event',offers=['gold','cache'])
    assert x.project(r)['offers']==['gold']
    with pytest.raises(ValueError):x.act(r,'a','choose',{'index':1},0,rng)
    r=x.act(r,'a','choose',{'index':0},0,rng)
    assert r['phase']=='route' and r['gold']==75 and r['completed']==10


@pytest.mark.parametrize('event',['gold','cache','training'])
def test_single_event_resolves_and_can_continue(event):
    rng=Random(3);r=drafted();r.update(phase='event',offers=[event])
    r=x.act(r,'a','choose',{'index':0},0,rng)
    if event=='cache':
        assert r['phase']=='reward' and not any(x.CATALOGUE[c]['hero'] for c in r['offers'])
        r=x.act(r,'a','skip',{},0,rng)
    elif event=='training':
        assert r['phase']=='upgrade'
        r=x.act(r,'a','upgrade',{'card':r['deck'][0]['id']},0,rng)
        assert r['gold']==10
    assert r['phase']=='route' and r['completed']==1 and r['battle'] is None
