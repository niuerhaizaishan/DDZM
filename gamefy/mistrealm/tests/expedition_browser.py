"""Real-browser smoke test against scripts/mistrealm_dev.py."""
import os
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright

base=os.environ.get('MISTREALM_DEV_URL','http://127.0.0.1:18771')
output=Path(os.environ.get('MISTREALM_SCREENSHOTS','/tmp/mistrealm-expedition-check'))
output.mkdir(parents=True,exist_ok=True)
with sync_playwright() as pw:
    browser=pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
    page=browser.new_page(viewport={'width':1366,'height':768});errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(base+'/v3/?player=expedition-test-'+uuid4().hex[:8])
    page.locator('#enter-game').click()
    page.locator('#tutorial-skip').click()
    page.locator('#expedition-mode').click()
    page.locator('[data-xp="start"]').click()
    for i in range(5):
        page.get_by_role('heading',name=f'选择起始牌 · {i+1} / 5').wait_for()
        choices=page.locator('[data-xp="pick"]')
        units=[c for c in choices.all() if c.locator('.xp-card-power').inner_text().isdigit()]
        (units[0] if units else choices.first).click()
        assert page.locator('[data-xp="pick"][aria-pressed="true"]').count()==1
        if i==0:page.screenshot(path=str(output/'draft-desktop.png'))
        page.locator('[data-xp="confirm-choice"]').click()
    page.locator('.xp-route').wait_for()
    assert page.locator('[data-hand]').count()==0
    page.locator('.xp-route button').filter(has_text='战斗').first.click()
    page.locator('[data-hand]').first.wait_for()
    page.locator('#pause-expedition').click()
    page.reload();page.locator('#enter-game').click()
    page.locator('#expedition-mode').click()
    page.locator('[data-hand]').first.wait_for()
    assert page.locator('[data-hand]').count()==5
    assert page.locator('.army-summary').count()==2
    assert page.locator('[data-battle-leader]').count()==0
    played=False
    for c in page.locator('[data-hand]').all():
        c.click()
        if page.locator('#use-hand').is_enabled():
            page.locator('#use-hand').click()
            if page.locator('.eligible').count():page.locator('.eligible').first.click()
            played=True;break
    assert played,'opening draft must allow this smoke scenario to play a card'
    def settled():
        page.wait_for_function('!document.querySelector("#main").inert && !document.querySelector("#game-shell").classList.contains("busy")')
    settled()
    for _ in range(20):
        if not page.locator('#confirm-choice').count():break
        if page.locator('[data-option]').count():page.locator('[data-option]').first.click()
        elif page.locator('[data-choice-card]').count():page.locator('[data-choice-card]').first.click()
        page.locator('#confirm-choice').click();settled()
    assert page.locator('[data-inspect]').count()>0
    page.locator('[data-inspect]').first.click()
    page.locator('.card-detail').wait_for();page.locator('#close-modal').click()
    page.locator('#view-log').click();page.locator('.match-history').wait_for();page.locator('#close-modal').click()
    page.screenshot(path=str(output/'battle-desktop.png'))
    for width,height in [(844,390),(390,844)]:
        page.set_viewport_size({'width':width,'height':height})
        page.screenshot(path=str(output/f'battle-{width}x{height}.png'))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('#pass').is_visible()
        assert page.locator('#pass').evaluate('el=>{const r=el.getBoundingClientRect(),m=document.querySelector("#main").getBoundingClientRect();return r.bottom<=m.bottom+1&&r.right<=m.right+1&&r.top>=m.top-1&&r.left>=m.left-1}'), 'pass button outside the screen'
    page.set_viewport_size({'width':1366,'height':768})
    page.locator('#pass').click();page.locator('#cancel-pass').click()
    assert page.locator('.army-summary').count()==2
    page.locator('#concede').click();page.locator('#confirm-concede').click();settled()
    page.locator('#leave').click()
    page.get_by_role('heading',name='本次远征结束').wait_for()
    assert not errors,errors
    browser.close()
print('Expedition browser smoke passed; screenshots:',output)
