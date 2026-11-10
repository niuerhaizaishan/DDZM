import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isClubNavigation,platformLoading} from '../publish/games/runtime.js';
import {toggleSelection} from '../publish/games/doudizhu/cards.js';

test('club navigation suppresses a second platform loading lifecycle',()=>{
  const loading={progress(){}};
  assert.equal(isClubNavigation('?club=1'),true);
  assert.equal(isClubNavigation('',true),true);
  assert.equal(platformLoading({loading},'?club=1'),null);
  assert.equal(platformLoading({loading},'',true),null);
  assert.equal(platformLoading({loading},''),loading);
});

test('doudizhu cards only toggle selection before the play button is pressed',()=>{
  assert.deepEqual([...toggleSelection(new Set(),12)],[12]);
  assert.deepEqual([...toggleSelection(new Set([12]),12)],[]);
  const source=readFileSync(new URL('../publish/games/doudizhu/game.js',import.meta.url),'utf8');
  assert.doesNotMatch(source,/dblclick|shouldPlayDrag|pointerdown/);
  assert.match(source,/played-cards/);
  assert.doesNotMatch(source,/p\.cards\.map\(cardLabel\)/);
});
