"""Reward and shop UI against a loopback dev DB; seeds only a new test UID."""
import json
import os
from pathlib import Path
from random import Random
import sqlite3
from urllib.parse import urlparse
from uuid import uuid4

from playwright.sync_api import sync_playwright
from dzmm_bot.core import mistrealm_expedition as x

base=os.environ.get('MISTREALM_DEV_URL','http://127.0.0.1:18771')
assert urlparse(base).hostname in ('127.0.0.1','localhost')
db=os.environ['MISTREALM_DEV_DB']
uid='expedition-reward-test-'+uuid4().hex[:8]
output=Path('/tmp/mistrealm-expedition-check');output.mkdir(exist_ok=True)


def saved():
    with sqlite3.connect(db) as conn:
        return json.loads(conn.execute('SELECT state FROM mistrealm_expeditions WHERE player_id=(SELECT id FROM mistrealm_players WHERE platform_uid=?)',(uid,)).fetchone()[0])


def seed(state):
    state['version']+=1
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE mistrealm_expeditions SET state=? WHERE player_id=(SELECT id FROM mistrealm_players WHERE platform_uid=?)',(json.dumps(state),uid))


with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
    page=browser.new_page(viewport={'width':1366,'height':768});errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base+'/v3/?player='+uid);page.locator('#enter-game').click();page.locator('#tutorial-skip').click()
    page.locator('#expedition-mode').click();page.locator('[data-xp=start]').click()
    page.get_by_role('heading',name='选择起始牌 · 1 / 5').wait_for()
    assert page.locator('[data-xp=skip]').count()==0
    r=saved();r.update(phase='reward',node=1,completed=1,deck=[],offers=x.offers(Random(7),next(iter(x.FACTIONS)),boss=True),gold=50)
    for _ in range(8):x.add_card(r,'xa01')
    for _ in range(2):x.add_card(r,'xb13')
    for _ in range(4):x.add_card(r,'xb09')
    seed(r)

    def reopen():
        page.reload();page.locator('#enter-game').click();page.locator('#expedition-mode').click()

    def settled():
        page.locator('.xp-working').wait_for(state='hidden')

    reopen();page.locator('[data-xp=pick][data-index="0"]').click()
    assert page.locator('[data-xp=confirm-choice]').is_enabled()
    page.screenshot(path=str(output/'boss-reward.png'))
    page.locator('[data-xp=confirm-choice]').click();page.locator('.xp-route').wait_for()
    r=saved();assert len(r['deck'])==15 and sum(x.CATALOGUE[c['card']]['hero'] for c in r['deck'])==3
    r.update(phase='reward',offers=['xb01','xb02','xb09']);seed(r);reopen()
    page.locator('[data-xp=skip]').click();page.locator('.xp-route').wait_for()
    r=saved();assert len(r['deck'])==15 and r['gold']==50
    r.update(phase='shop',offers=['xa09','xb02','xb03']);seed(r);reopen()
    page.locator('[data-xp=buy][data-index="0"]').click();settled()
    r=saved();assert len(r['deck'])==16 and r['gold']==35 and len(r['offers'])==2
    page.locator('[data-xp=shop-tab][data-tab=sell]').click()
    page.locator('[data-xp=pick-sell]').last.click();page.locator('[data-xp=sell]').click();settled()
    r=saved();assert len(r['deck'])==15 and r['gold']==40
    page.locator('[data-xp=shop-tab][data-tab=upgrade]').click()
    page.locator('[data-xp=pick-upgrade]').first.click();page.locator('[data-xp=upgrade]').click();settled()
    r=saved();assert r['gold']==30 and r['deck'][0]['expedition_upgrade']==2 and r['upgrade_bought']
    assert page.locator('[data-xp=upgrade]').count()==0
    reopen();page.locator('[data-xp=shop-tab][data-tab=upgrade]').click()
    assert page.locator('[data-xp=upgrade]').count()==0
    page.locator('[data-xp=leave]').click();page.locator('.xp-route').wait_for()
    assert saved()['battle'] is None
    r=saved();r.update(phase='route',offers=['event']);seed(r);reopen()
    page.locator('[data-xp=route]').click();page.locator('.xp-event').wait_for()
    assert page.locator('[data-xp=route]').count()==1
    event=saved()['offers'];reopen();assert saved()['offers']==event
    page.locator('.xp-event').wait_for();page.screenshot(path=str(output/'single-event.png'))

    # Check each shop service at desktop and rotated phone sizes.
    r=saved();r.update(phase='shop',offers=['xa09','xb02','xb03'],upgrade_bought=False);seed(r);reopen()
    for width,height in [(1366,768),(844,390),(390,844)]:
        page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(200)
        for tab in ('buy','sell','upgrade'):
            page.locator(f'[data-xp=shop-tab][data-tab={tab}]').click()
            if tab!='buy':page.locator(f'[data-xp=pick-{tab}]').first.click()
            button=page.locator('[data-xp=buy]').first if tab=='buy' else page.locator(f'[data-xp={tab}]')
            button.scroll_into_view_if_needed()
            assert page.locator('[data-xp=shop-tab][data-tab=buy]').evaluate('el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1}')
            assert button.is_enabled()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert button.evaluate('el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1}')
            page.screenshot(path=str(output/f'shop-{tab}-{width}x{height}.png'))
    assert not errors,errors
    browser.close()
print('Expedition unlimited rewards, skip, shop buy/sell/upgrade, reload, single event and mobile UI passed')
