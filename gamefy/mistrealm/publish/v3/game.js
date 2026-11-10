import {setupExpedition} from './expedition.js';
import {setupProfile} from './profile.js';
import {setupGameAudio} from './audio.js';
import {selectionOption,toggleSelection} from './multi-select.js';
import {battleStatus,groupMatchActions} from './battle-info.js';
import {stepText,setupEffectFeedback} from './effect-feedback.js';
import {filterCatalogue,EFFECT_FILTERS,deckCounts,deckChanged,cardSkillLabel} from './catalogue.js';
import {setupTutorial} from './tutorial.js';
import {setupRanked,rankResult,rankBadge} from './ranked.js';
import {setupSocial} from './social.js';
import {setupScreen} from './screen.js';
import {V3Client,remainingSeconds} from './client.js';
import {CONFIG} from './config.js';
const client=new V3Client({sdk:window.dzmm,apiBase:CONFIG.apiBase});
const $=id=>document.getElementById(id),main=$('main');
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rows=['近战','远程','攻城'];
let data,tutorialScenes,profile,decks=[],selectedDeck=null,room=null,receivedAt=0,busy=false,selection=null,playSelection=false,picks=new Set(),draft=null,builderPage=0;
let queue=null,queueEpoch=0,queueTimer=null;
let connectionLost=false,matchLogAll=false,recoveredVersion=null,deckSaving=false,deckSaveError='';
let builderFilters={query:'',row:'all',type:'all',effect:'all'},choiceIds=[],choiceKey='',choiceSelection=null,choiceTarget=null,choiceCollapsed=false,choiceNotice='',builderOriginal=null;
let revealQueue=[],revealTimer=null,revealCurrent=null,latestRoom=null;
const effectFeedback=setupEffectFeedback({shell:$('game-shell'),getCard:id=>cardData(id),getSeat:()=>room.state.seat});
let gameSettings={animations:true,sound:false};
const gameAudio=setupGameAudio(()=>gameSettings.sound);
let channelOpen=false,channelItems=[],channelKnown=new Set(),channelLoaded=false,returnToStory=false;
const cardData=c=>{const d=data.transforms[c.form]||data.cards[c.card]||data.cards[c]||expedition.catalogue()?.cards[c.card||c];return c.expedition_upgrade?{...d,power:d.power+c.expedition_upgrade}:d;};
const expedition=setupExpedition({main,client,getData:()=>data,esc,modal,home,showBattle:showExpeditionBattle,closeBattle:closeExpeditionBattle});
const selected=()=>decks.find(d=>d.id===selectedDeck)||decks[0];
const desc=c=>c.text+(c.abilities.includes('bond')&&!c.text.includes('条件战力')?' 同袍：本排有另一张同名己方单位时，自身条件战力＋2，不叠加。':'');
function feedback(text,error=false){$('feedback').textContent=text;$('feedback').classList.toggle('error',error);}
function bind(id,fn){const n=$(id);if(n)n.onclick=fn;}
function images(){document.querySelectorAll('img').forEach(img=>{img.onerror=()=>{img.hidden=true;img.parentElement.classList.add('missing-art');};});}
const emblem=id=>`<img class="faction-emblem" src="${expedition.catalogue()?.factions[id]?'./expedition/'+id+'.svg':'../assets/classic/ui/'+id+'.svg'}" alt="">`;
const factionName=id=>data.factions[id]||expedition.catalogue()?.factions[id];
function button(text,id,cls='primary'){return `<button id="${id}" class="${cls}">${text}</button>`;}
function modal(html,view=''){ $('modal').dataset.view=view;$('modal-content').innerHTML=html;if(!$('modal').open)$('modal').showModal();syncChannel();images();}
function identity(p,self){const avatar=p.avatar?.startsWith('https://')||(p.is_bot&&/^\.\.\/assets\/bots\/lorelei-\d{2}\.svg$/.test(p.avatar))?p.avatar:null;return `<div class="identity"><span class="avatar"><span>${esc((p.name||'旅')[0])}</span>${avatar?`<img src="${esc(avatar)}" alt="" referrerpolicy="no-referrer">`:''}</span><div><b>${esc(p.name||'旅人')}</b><small>${room?.state.spectator?(self?'观战好友':'对手'):self?'你':'对手'}${p.rank_tier?` · ${esc(p.rank_tier.name)} ${p.rank_rating}`:''}${p.honor?` · <span class="rank-honor">${rankBadge(p.honor.badge,p.honor.title)}${esc(p.honor.title)}</span>`:''}</small></div></div>`;}
function card(c,attrs='',chosen=false){const d=cardData(c);return `<button class="card ${d.hero?'hero-card':''} ${chosen?'selected':''}" ${attrs}><img src="${esc(d.art)}" alt="" loading="lazy"><span class="art-sigil">${esc(data.factions[d.faction]?.slice(0,2)||'雾境')}</span><span class="power ${d.type==='special'?'spell-badge':''}" role="img" aria-label="${d.type==='unit'?'战力 '+esc(c.power??d.power):d.type==='leader'?'领袖':d.persistent?'持续术':'即时术'}">${d.type==='unit'?`<span>${esc(c.power??d.power)}</span>`:`<img src="../assets/classic/ui/${d.type==='leader'?'crown':'ritual'}.svg" alt="">`}</span><span class="card-copy"><b>${esc(d.name)}</b><small>${esc(cardSkillLabel(d))}</small></span></button>`;}
function statusTags(c){return (c.ui_status||[]).length?`<div class="card-status-list">${c.ui_status.map(x=>`<span data-tone="${esc(x.tone)}">${esc(x.text)}</span>`).join('')}</div>`:'';}
function shortStatus(c){const statuses=c.ui_status||[];return esc((statuses.find(x=>x.tone==='off')||statuses[0])?.short||'');}
function inspectCard(c,back=false){const d=cardData(c),p=c.power_detail;const catalogue=back?builderCards():[],index=catalogue.findIndex(([id])=>id===c.card);
 modal(`<div class="card-detail"><img src="${esc(d.art)}" alt="${esc(d.name)}"><div><p class="eyebrow">${esc(factionName(d.faction)||'中立')} · ${d.hero?'英雄单位':d.type==='leader'?'领袖':d.type==='unit'?'普通单位':d.persistent?'持续术':'即时术'}</p><h2>${esc(d.name)}</h2>${statusTags(c)}<p>${esc(desc(d)||'依靠基础战力争夺本局优势。')}</p><p>基础战力 ${d.power} · ${d.rows.map(r=>rows[r]).join(' / ')||'术卡位置'}</p>${p?`<section class="power-breakdown"><h3>当前战力 ${p.power}</h3><p>基础 ${p.base} + 强化 ${p.boost} + 条件 ${p.condition} − 伤害 ${p.damage}${p.sealed?' · 已封印':''}</p></section>`:''}${back?`<div class="quantity detail-quantity"><button id="detail-minus" aria-label="减少携带数量" ${!draft.counts[c.card]?'disabled':''}>−</button><b>携带 ${draft.counts[c.card]||0} / ${d.copies}</b><button id="detail-plus" aria-label="增加携带数量" ${(draft.counts[c.card]||0)>=d.copies?'disabled':''}>＋</button></div>`:''}</div></div>${back?`<nav class="card-pagination"><button id="previous-card" ${index===0?'disabled':''}>上一张</button><span>${index+1} / ${catalogue.length}</span><button id="next-card" ${index===catalogue.length-1?'disabled':''}>下一张</button></nav>${button('返回组牌','back-builder','secondary')}`:''}`,back?'card-editor':'card-detail');
 if(back){bind('back-builder',()=>{builderPage=Math.floor(index/builderPageSize());builderView();});bind('previous-card',()=>inspectCard({card:catalogue[index-1][0]},true));bind('next-card',()=>inspectCard({card:catalogue[index+1][0]},true));for(const [key,delta] of [['minus',-1],['plus',1]])bind('detail-'+key,()=>{draft.counts[c.card]=(draft.counts[c.card]||0)+delta;inspectCard(c,true);});}}

function leaderStatus(p){return p.leader_disabled?'已禁用':p.leader_used?'已使用':'未使用';}
function openingLeaders(){return `<div class="opening-leaders" aria-label="双方领袖能力">${room.state.players.map((p,i)=>`<article><small>${i===room.state.seat?'你的领袖':'对手领袖'} · ${leaderStatus(p)}</small><h3>${esc(data.cards[p.leader].name)}</h3>${identity(p,i===room.state.seat)}<p>${esc(desc(data.cards[p.leader]))}</p></article>`).join('')}</div>`;}
function inspectLeader(seat,confirm=false){
 const s=room?.state,p=s?.players[seat];if(!p?.leader){$('modal').close();return;}
 const d=data.cards[p.leader],canUse=seat===s.seat&&(s.legal_moves||[]).some(m=>m.action==='leader');
 modal(`<section class="leader-detail"><p class="eyebrow">${s.spectator?(seat===s.seat?'好友领袖':'对手领袖'):seat===s.seat?'你的领袖':'对手领袖'} · ${esc(factionName(p.faction))}</p><h2>${esc(d.name)}</h2><strong class="leader-status">${leaderStatus(p)}</strong><p class="leader-effect">${esc(desc(d))}</p><p class="muted">整场对局只能发动一次，发动会消耗本次行动。</p>${confirm?`<p>${canUse?'确认后发动技能；需要目标时，再选择目标。':'当前无法发动，请关闭后查看对局状态。'}</p><div class="actions">${canUse?button('确认发动','confirm-leader'):''}${button('返回对战','cancel-leader','secondary')}</div>`:''}</section>`,confirm?'leader-confirm':'leader-detail');
 $('modal').dataset.leaderSeat=seat;
 bind('cancel-leader',()=>$('modal').close());
 bind('confirm-leader',()=>{
  if(room?.state.seat!==seat||!(room.state.legal_moves||[]).some(m=>m.action==='leader')){inspectLeader(seat,true);return;}
  run(async()=>{$('modal').close();await act('leader');});
 });
}

async function run(fn){if(busy)return;busy=true;updateBattleStatus();$('game-shell').classList.add('busy');try{await fn();feedback('已连接 · 牌局由服务器同步');}catch(e){feedback(e.message,true);if(e.status===409&&room&&room.state.mode!=='expedition'){try{accept(await client.snapshot());}catch{}}}finally{busy=false;$('game-shell').classList.remove('busy');updateBattleStatus();}}
function accept(value){
 if(value.state.phase!=='closed'&&latestRoom?.room_id===value.room_id&&latestRoom.match_id===value.match_id&&latestRoom.state.version>value.state.version)return;
 if(value.state.phase==='closed'&&client.watching){leaveSpectate();feedback('好友对局已结束，已退出观战');return;}
 if(value.state.phase==='closed'){const story=returnToStory||room?.state?.mode==='story';client.stop();clearReveal();room=null;latestRoom=null;if($('modal').open)$('modal').close();if(story)storyView();else home();return;}
 if(value.state.rules_version===3&&value.state.balance_revision!==2){client.stop();location.replace(new URL('../',import.meta.url).href+location.search+location.hash);return;}
 if(value.state.rules_version!==3){client.stop();location.replace((value.state.rules_version===2?'../classic/':'../')+location.search+location.hash);return;}
 const recovering=connectionLost;connectionLost=false;
 const previous=latestRoom;latestRoom=value;client.state=value;client.roomId=value.room_id;receivedAt=performance.now();returnToStory=value.state.mode==='story';
 if(recovering){clearReveal();room=value;selection=null;playSelection=false;recoveredVersion=value.state.version;render();updateBattleStatus();feedback('连接已恢复 · 第'+value.state.round+'局 · '+battleStatus(value.state));return;}
 syncActionLog(previous,value);
}
function enter(value){if(!value.state.spectator)client.watching=null;ranked.close();queue=null;clearTimeout(queueTimer);queueEpoch++;selection=null;playSelection=false;picks.clear();client.stop();clearReveal();room=null;latestRoom=null;accept(value);if(!room)return;client.follow(value.room_id,accept,e=>{if(client.watching&&(e.status===403||e.status===404||e.status===409)){leaveSpectate();feedback(e.message,true);}else {connectionLost=true;updateBattleStatus();feedback(e.message+'，正在重连…',true);}});}
function showExpeditionBattle(run){
 const id=`expedition:${run.id}:${run.battle_serial}`;
 if(room?.room_id!==id){client.stop();clearReveal();room=null;latestRoom=null;selection=null;playSelection=false;}
 const state={...run.battle,mode:'expedition',players:run.battle.players.map((p,i)=>({...p,name:i?factionName(p.faction):profile.name}))};
 accept({room_id:id,match_id:id,state});
}
function closeExpeditionBattle(){
 if(room?.state.mode!=='expedition')return;
 client.stop();clearReveal();room=null;latestRoom=null;client.state=null;client.roomId=null;
 main.onclick=null;$('game-shell').classList.remove('battle','preparing');syncChannel();
}
async function spectate(player){
 client.stop();client.syncState=null;client.state=null;
 client.watching={uid:player.uid,match_id:player.spectate_match_id};
 try{const value=await client.snapshot(player.spectate_room_id);if(value.state.phase==='closed')throw new Error('这场对局已结束');enter(value);}
 catch(e){client.watching=null;client.syncState=null;throw e;}
}
function leaveSpectate(){
 client.stop();client.watching=null;client.syncState=null;client.state=null;client.roomId=null;
 clearReveal();room=null;latestRoom=null;if($('modal').open)$('modal').close();home();
}
async function act(action,payload={}){
 if(room?.state.spectator)return;
 if(room?.state.mode==='expedition'){
  if(revealCurrent||revealQueue.length||effectFeedback.active)return;
  if(action==='leave'){expedition.continueJourney();return;}
  await expedition.battleAction(action,payload);selection=null;playSelection=false;render();return;
 }
 if(connectionLost)throw new Error('正在恢复连接，请等待牌局同步后再操作');
 if(revealCurrent||revealQueue.length||effectFeedback.active)return;
 for(let attempt=0;attempt<3;attempt++){
  try{accept(await client.action(action,payload));break;}
  catch(e){
   if(e.status!==409||!['lock','unlock','mulligan','rematch'].includes(action)||attempt===2)throw e;
   accept(await client.snapshot());
   if(!room)break;
   const s=room.state,p=s.players[s.seat];
   if(['lock','unlock'].includes(action)&&(s.phase!=='waiting'||p.locked===(action==='lock')))break;
   if(action==='mulligan'&&(s.phase!=='mulligan'||p.mulligan_done))break;
   if(action==='rematch'&&(s.phase!=='finished'||p.rematch))break;
  }
 }
 selection=null;playSelection=false;render();
}

function syncChannel(){
 const channel=$('channel'),host=$('modal').open?$('modal'):$('game-shell');
 if(channel.parentElement!==host)host.append(channel);
 channel.hidden=!profile;$('channel-challenge').hidden=!!room||!!queue;
 document.querySelectorAll('[data-channel-code]').forEach(n=>n.disabled=!!room||!!queue);
 social.sync();
}
function channelLabel(item){return item.kind==='challenge'?'发布了约战':item.text;}
function renderChannel(){
 const last=channelItems.at(-1);$('channel-preview').textContent=last?`${last.player.name}：${channelLabel(last)}`:'暂时还没有人发言';
 const list=$('channel-messages'),atBottom=list.scrollHeight-list.scrollTop-list.clientHeight<30,scrollTop=list.scrollTop;
 if(!channelLoaded){channelKnown=new Set(channelItems.map(item=>item.id));channelLoaded=true;}
 list.innerHTML=channelItems.map(item=>`<article class="channel-message"><span class="channel-avatar">${esc((item.player.name||'旅')[0])}${item.player.avatar?.startsWith('https://')?`<img src="${esc(item.player.avatar)}" alt="" referrerpolicy="no-referrer">`:''}</span><div><button class="channel-player-name" data-social-player="${esc(item.player.uid)}">${esc(item.player.name)}</button><span class="channel-presence ${item.player.online?'online':'offline'}">${item.player.online?'在线':'离线'}</span><small>${new Date(item.created_at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})}</small>${item.kind==='challenge'?`<section class="challenge-card"><strong>公开约战</strong><p>${item.challenge.status==='waiting'?'等待对手加入':'房间已经结束'}</p>${item.challenge.status==='waiting'?`<button data-channel-code="${esc(item.challenge.code)}">加入对局</button>`:''}</section>`:`<p>${esc(item.text)}</p>`}</div></article>`).join('')||'<p class="channel-empty">成为第一个发言的人吧。</p>';
 document.querySelectorAll('[data-social-player]').forEach(node=>node.onclick=()=>personal.open(node.dataset.socialPlayer));
 document.querySelectorAll('[data-channel-code]').forEach(node=>node.onclick=()=>run(async()=>enter(await client.join(node.dataset.channelCode,selected().id))));
 if(channelOpen){list.scrollTop=atBottom?list.scrollHeight:scrollTop;channelKnown=new Set(channelItems.map(item=>item.id));$('channel-unread').hidden=true;}
 else{
  const unread=channelItems.filter(item=>!channelKnown.has(item.id)).length;
  $('channel-unread').textContent=unread;$('channel-unread').hidden=!unread;
 }
 syncChannel();images();
}
function toggleChannel(open){
 channelOpen=open;$('channel-panel').hidden=!open;$('channel').classList.toggle('open',open);$('channel-toggle').setAttribute('aria-expanded',String(open));
 if(open){channelKnown=new Set(channelItems.map(item=>item.id));$('channel-unread').hidden=true;renderChannel();$('channel-messages').scrollTop=$('channel-messages').scrollHeight;}
 else $('channel-toggle').focus();
 if(open)void social.refresh();
}
async function publishChallenge(value){await client.channelChallenge(value.room_id);enter(value);}

async function storyView(){
 syncChannel();$('game-shell').classList.remove('battle');returnToStory=true;
 try{
  const progress=await client.story(),deck=selected();
  main.innerHTML=`<section class="story-select"><div class="story-heading"><div><p class="eyebrow">MISTREALM · SOLO STORY</p><h1>雾境纪事</h1><p>独自穿过五段迷雾。剧情进度会自动保存。</p></div>${button('返回大厅','story-back','secondary')}</div><div class="story-chapters">${progress.chapters.map(item=>`<article class="story-chapter ${item.locked?'locked':''}"><span>第 ${item.id} 章</span><h2>${esc(item.title)}</h2><p>${esc(item.summary)}</p><small>对手 · ${esc(item.enemy)}</small>${item.completed?'<b>已通关</b>':''}${item.locked?'<button disabled>尚未解锁</button>':`<button data-story="${item.id}">${item.completed?'再次挑战':'开始关卡'}</button>`}</article>`).join('')}</div><div class="story-deck"><span>当前军团</span><b>${esc(deck.name)}</b><small>${esc(data.factions[deck.faction])}</small>${button('更换军团','story-deck-change','secondary')}</div></section>`;
  bind('story-back',()=>{returnToStory=false;home();});bind('story-deck-change',deckPicker);
  document.querySelectorAll('[data-story]').forEach(node=>node.onclick=()=>run(async()=>enter(await client.startStory(Number(node.dataset.story),selected().id))));
 }catch(e){feedback(e.message,true);home();}
}

function home(){expedition.close();if(room)return render();ranked.close();main.onclick=null;$('game-shell').classList.remove('preparing','spectating');returnToStory=false;syncChannel();$('game-shell').classList.remove('battle');const d=selected();main.innerHTML=`<section class="hero"><div class="hero-copy"><p class="eyebrow">FIVE FACTIONS · ONE LAST CARD</p><h1>王冠将倾<br>群鸦将至</h1><p class="intro">组建你的军团。在三排战场上争夺优势，<br>也为下一局，留住一张底牌。</p><button id="open-profile" class="profile-entry" aria-label="打开个人中心">${identity(profile,true)}<span>个人中心 ›</span></button><div class="deck-choice"><small>当前出战牌组 · 已保存</small><h2 id="selected-deck">${esc(d?.name||'尚无牌组')}</h2><p>${esc(data.factions[d?.faction])} · ${esc(data.cards[d?.leader]?.name)}</p><div class="actions">${button('更换军团','choose-deck','secondary')}${button('编辑牌组','edit-deck','secondary')}</div></div><div class="play-modes"><button id="ranked-mode" class="rank-entry" aria-label="排位赛，查看段位与赛季"><svg class="rank-entry-crest" viewBox="0 0 120 140" aria-hidden="true"><path class="crest-halo" d="M60 5 111 42 100 101 60 134 20 101 9 42Z"/><path class="crest-frame" d="M60 18 97 46 89 94 60 119 31 94 23 46Z"/><path class="crest-crown" d="m37 55 12 10 11-24 11 24 12-10-5 30H42Z"/><path class="crest-detail" d="M42 91h36M60 98v9M17 68l-8 13 15 9M103 68l8 13-15 9M24 102l-4 11 19 3M96 102l4 11-19 3"/><path class="crest-gem" d="m60 59 5 10-5 10-5-10Z"/></svg><span class="rank-entry-copy"><small>RANKED · 王冠征途</small><strong>排位赛</strong><span id="home-rank-status">争夺段位 · 赢取赛季荣誉</span></span><span class="rank-entry-go">踏上征途 <b>→</b></span></button><button id="story-mode" class="mode-card"><small>单人 · 随时可玩</small><strong>剧情模式</strong><span>五章旅程，对抗规则 AI</span></button><button id="quick-match" class="mode-card"><small>双人 · 在线匹配</small><strong>休闲对战</strong><span>寻找对手，开始一场雾境对决</span></button></div><div class="actions home-room">${button('远征 · 三族试炼','expedition-mode','secondary')}${button('自定义房间','custom-room','secondary')}${button('新手教学','tutorial-replay','secondary')}</div></div><aside class="home-note"><img class="home-portrait" src="${esc(data.cards[d?.leader]?.art)}" alt=""><div><span>120</span><p>张原创卡牌<br>5 个阵营 · 10 位领袖</p><small>四格战列 · 条件英雄<br>伤害 · 死亡 · 三格术区</small></div></aside></section>`;
 bind('choose-deck',()=>deckPicker());bind('edit-deck',()=>builder());bind('story-mode',storyView);bind('expedition-mode',expedition.open);bind('open-profile',()=>personal.open());bind('ranked-mode',()=>run(ranked.open));bind('quick-match',()=>run(startQueue));bind('custom-room',customRoom);bind('tutorial-replay',()=>tutorial.start());images();const rankStatus=$('home-rank-status');void client.rankedProfile().then(info=>{if(rankStatus.isConnected)rankStatus.textContent=`S${info.season.id} · ${info.player.tier.name} ${info.player.rating} 分`;}).catch(()=>{});}
function customRoom(){
 modal(`<section class="custom-room"><p class="eyebrow">PRIVATE MATCH</p><h2>自定义房间</h2><p class="muted">与朋友约一场雾境对决</p><div class="room-options"><section><h3>创建房间</h3><p>创建后分享房间码，邀请朋友加入。</p>${button('创建房间','create-room')}</section><section><h3>加入房间</h3><label for="room-code-input">输入朋友分享的房间码</label><div id="join-form"><input id="room-code-input" placeholder="六位房间码" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="off" aria-label="房间码" aria-describedby="join-feedback"><button id="join-room" type="button">加入房间</button></div><p id="join-feedback" class="join-feedback" role="status" aria-live="polite" hidden></p></section></div></section>`,'custom-room');
 bind('create-room',()=>run(async()=>{const value=await client.create(selected().id);$('modal').close();enter(value);}));
 bind('join-room',joinRoom);$('room-code-input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();joinRoom();}};
}
function joinRoom(){
 if(busy)return;
 const code=$('room-code-input').value.trim(),hint=$('join-feedback'),button=$('join-room');
 hint.hidden=false;hint.classList.remove('error');
 if(!/^[0-9]{6}$/.test(code)){hint.textContent='请输入6位数字房间码';hint.classList.add('error');hint.scrollIntoView({block:'nearest'});return;}
 return run(async()=>{
  hint.textContent='正在加入房间…';hint.scrollIntoView({block:'nearest'});button.disabled=true;button.textContent='正在加入…';
  try{const value=await client.join(code,selected().id);$('modal').close();enter(value);}
  catch(e){if(e.status===404)e.message='房间不存在，请检查房间码';hint.textContent=e.message;hint.classList.add('error');hint.scrollIntoView({block:'nearest'});throw e;}
  finally{if(button.isConnected){button.disabled=false;button.textContent='加入房间';}}
 });
}
function deckPicker(){modal(`<p class="eyebrow">YOUR ARMIES</p><h2>选择出战军团</h2><div class="deck-list">${decks.map(d=>`<button data-deck="${d.id}" class="deck-tile"><b>${esc(d.name)}</b><small>${esc(data.factions[d.faction])} · ${esc(data.cards[d.leader].name)}</small></button>`).join('')}</div><h3>建立新牌组</h3><div class="actions">${Object.entries(data.factions).map(([id,name])=>`<button data-new="${id}">${esc(name)}</button>`).join('')}</div>`);
 document.querySelectorAll('[data-deck]').forEach(n=>n.onclick=()=>run(async()=>{const id=n.dataset.deck;if(room)await act('select_deck',{deck_id:id});await client.selectDeck(id);selectedDeck=id;$('modal').close();if(!room)home();}));
 document.querySelectorAll('[data-new]').forEach(n=>n.onclick=()=>builder({...structuredClone(data.starters.find(d=>d.faction===n.dataset.new)),id:null}));}
function builderCards(){return filterCatalogue(data.cards,draft.faction,builderFilters);}
function builderPageSize(){const viewport=$('game-viewport');return (viewport.clientWidth>=900?6:viewport.clientWidth>=600?4:3)*(viewport.clientHeight>=850?2:1);}
function builder(value=selected()){draft=structuredClone(value);builderOriginal=structuredClone(value);deckSaveError='';builderPage=0;builderFilters={query:'',row:'all',type:'all',effect:'all'};builderView();}
function builderView(){const stats=deckCounts(data.cards,draft.counts);const unitCount=Object.entries(draft.counts).reduce((n,[id,v])=>n+(data.cards[id].type==='unit'?v:0),0),specialCount=Object.entries(draft.counts).reduce((n,[id,v])=>n+(data.cards[id].type==='special'?v:0),0),heroCount=Object.entries(draft.counts).reduce((n,[id,v])=>n+(data.cards[id].hero?v:0),0);
 const catalogue=builderCards(),pageSize=builderPageSize(),pages=Math.max(1,Math.ceil(catalogue.length/pageSize));builderPage=Math.min(builderPage,pages-1);
 modal(`<section id="builder"><div class="builder-heading"><h2>编制军团</h2><input id="deck-name" aria-label="牌组名称" value="${esc(draft.name)}" maxlength="40"></div><div class="builder-counts ${unitCount<14||specialCount>6||unitCount+specialCount!==20||heroCount>2?'invalid':''}">总数 <b>${unitCount+specialCount}</b>/20 · 单位 ${unitCount}/至少14 · 英雄 ${heroCount}/最多2 · 术卡 ${specialCount}/最多6<small class="deck-composition">近战 ${stats.rows[0]} · 远程 ${stats.rows[1]} · 攻城 ${stats.rows[2]}<br>即时术 ${stats.instant} · 持续术 ${stats.persistent}${stats.flexible?` · 多战列单位 ${stats.flexible}（分别计入）`:""}</small></div><div class="leader-options" aria-label="选择领袖">${Object.entries(data.cards).filter(([,c])=>c.type==='leader'&&c.faction===draft.faction).map(([id,c])=>`<button data-leader="${id}" aria-pressed="${draft.leader===id}" class="${draft.leader===id?'chosen':''}">${esc(c.name)}</button>`).join('')}</div><p class="leader-description">${esc(desc(data.cards[draft.leader]))}</p><div class="builder-search"><input id="card-search" type="search" autocomplete="off" aria-label="搜索卡牌名称或效果" placeholder="搜索名称或效果" value="${esc(builderFilters.query)}"><button id="card-filters">筛选${Object.entries(builderFilters).some(([k,v])=>k!=='query'&&v!=='all')?' · 已开启':''}</button><button id="clear-card-filters" aria-label="清除搜索与筛选">清除</button></div><div class="builder-grid">${!catalogue.length?'<p class="builder-empty">没有符合条件的卡牌<br>试试其他关键词，或清除筛选</p>':''}${catalogue.slice(builderPage*pageSize,(builderPage+1)*pageSize).map(([id,c])=>`<article>${card({card:id},`data-inspect="${id}"`)}<div class="quantity"><button data-minus="${id}" aria-label="移除${esc(c.name)}" ${!draft.counts[id]?'disabled':''}>−</button><b>${draft.counts[id]||0} / ${c.copies}</b><button data-plus="${id}" aria-label="添加${esc(c.name)}" ${(draft.counts[id]||0)>=c.copies?'disabled':''}>＋</button></div></article>`).join('')}</div><nav class="card-pagination"><button id="previous-page" ${builderPage===0?'disabled':''}>上一页</button><span>${builderPage+1} / ${pages} · ${catalogue.length}张</span><button id="next-page" ${builderPage===pages-1?'disabled':''}>下一页</button></nav><div class="builder-save"><small id="deck-save-status" role="status"></small>${button('保存牌组','save-deck')}${button('另存副本','copy-deck','secondary')}${button('撤销编辑','undo-deck','secondary')}</div></section>`,'builder');
 updateDeckSaveStatus();
 $('deck-name').oninput=e=>{draft.name=e.target.value;deckSaveError='';updateDeckSaveStatus();};
 const searchCards=e=>{builderFilters.query=e.target.value;if(e.isComposing)return;const start=e.target.selectionStart,end=e.target.selectionEnd;builderPage=0;builderView();$('card-search').focus({preventScroll:true});if(start!==null)$('card-search').setSelectionRange(start,end);};
 $('card-search').oninput=searchCards;$('card-search').oncompositionend=searchCards;
 bind('card-filters',builderFilterView);bind('clear-card-filters',()=>{builderFilters={query:'',row:'all',type:'all',effect:'all'};builderPage=0;builderView();});
 document.querySelectorAll('[data-inspect]').forEach(n=>n.onclick=()=>inspectCard({card:n.dataset.inspect},true));
 document.querySelectorAll('[data-leader]').forEach(n=>n.onclick=()=>{draft.leader=n.dataset.leader;builderView();});
 for(const key of ['plus','minus'])document.querySelectorAll('[data-'+key+']').forEach(n=>n.onclick=()=>{draft.counts[n.dataset[key]]=(draft.counts[n.dataset[key]]||0)+(key==='plus'?1:-1);builderView();});
 bind('previous-page',()=>{builderPage--;builderView();});bind('next-page',()=>{builderPage++;builderView();});
 const saveDeck=async value=>{
  deckSaving=true;deckSaveError='';updateDeckSaveStatus();
  try{const d=await client.saveDeck(value);decks=[...decks.filter(x=>x.id!==d.id),d];selectedDeck=d.id;draft=structuredClone(d);builderOriginal=structuredClone(d);$('modal').close();home();}
  catch(e){deckSaveError='保存失败，修改已保留';throw e;}
  finally{deckSaving=false;updateDeckSaveStatus();}
 };
 bind('save-deck',()=>run(()=>saveDeck(draft)));
 bind('copy-deck',()=>run(()=>saveDeck({...structuredClone(draft),id:null,name:draft.name.slice(0,35)+' · 副本'})));
 bind('undo-deck',()=>{draft=structuredClone(builderOriginal);builderView();});} 
function updateDeckSaveStatus(){
 const node=$('deck-save-status');if(!node)return;
 node.textContent=deckSaving?'正在保存…':deckSaveError||(!draft.id?'新牌组 · 尚未保存':deckChanged(draft,builderOriginal)?'有未保存修改':'已保存 · '+(draft.id===selectedDeck?'当前出战牌组':'未设为出战'));
 node.dataset.dirty=String(deckChanged(draft,builderOriginal)||!draft.id);
}
function builderFilterView(){
 const group=(key,title,items)=>`<fieldset><legend>${title}</legend><div class="filter-options">${items.map(([value,name])=>`<button data-filter="${key}" data-value="${value}" aria-pressed="${builderFilters[key]===value}">${name}</button>`).join('')}</div></fieldset>`;
 modal(`<section class="builder-filter-view"><p class="eyebrow">CARD CATALOGUE</p><h2>筛选卡牌</h2>${group('row','可部署战列',[['all','全部战列'],['0','近战'],['1','远程'],['2','攻城']])}${group('type','卡牌类型',[['all','全部类型'],['normal','普通单位'],['hero','英雄'],['instant','即时术'],['persistent','持续术']])}${group('effect','卡牌效果',EFFECT_FILTERS)}<div class="filter-footer"><span>符合条件 ${builderCards().length} 张</span>${button('查看卡牌','apply-card-filters')}${button('重置筛选','reset-card-filters','secondary')}</div></section>`,'builder-filters');
 document.querySelectorAll('[data-filter]').forEach(n=>n.onclick=()=>{builderFilters[n.dataset.filter]=n.dataset.value;builderPage=0;builderFilterView();});
 bind('apply-card-filters',builderView);bind('reset-card-filters',()=>{builderFilters={query:'',row:'all',type:'all',effect:'all'};builderPage=0;builderFilterView();});
}
$('game-shell').addEventListener('screenresize',()=>{if(document.activeElement?.matches('input,textarea'))return;if($('modal').open&&$('modal').dataset.view==='builder')builderView();});
document.addEventListener('keydown',e=>{if(!$('modal').open||e.target.matches('input,textarea')||!['ArrowLeft','ArrowRight'].includes(e.key))return;const view=$('modal').dataset.view;if(!['builder','card-editor'].includes(view))return;const id=(e.key==='ArrowLeft'?'previous-':'next-')+(view==='builder'?'page':'card'),control=$(id);if(control&&!control.disabled){e.preventDefault();control.click();}});
async function startQueue(mode='casual'){const epoch=++queueEpoch;const value=await client.startMatchmaking(selected().id,mode);if(epoch!==queueEpoch)return;updateQueue(value);}
function updateQueue(value){ranked.close();if(value.status==='matched'){enter(value.room);return;}if(value.status!=='waiting'){queue=null;home();if(value.message)feedback(value.message);return;}queue={...value,elapsed_ms:(value.elapsed_ms||0)+(value===queue?performance.now()-value.receivedAt:0),receivedAt:performance.now()};main.innerHTML=`<section class="match-panel"><p class="eyebrow">${value.mode==='ranked'?'RANKED · 排位赛':'QUICK MATCH · 休闲对战'}</p><div class="match-mark">◇</div><h2>群鸦正在寻找对手</h2><p>出战牌组已锁定：${esc(value.deck?.name||'已锁定军团')}</p><p class="muted">正在为你寻找对手。<br>匹配成功后同时揭晓阵营与领袖。</p><p class="match-elapsed">已等待 <strong id="elapsed">${Math.floor(queue.elapsed_ms/1000)}</strong> 秒</p>${button('取消匹配','cancel-match')}<small>等待期间请保持页面在线</small></section>`;
 syncChannel();bind('cancel-match',()=>run(async()=>{queueEpoch++;clearTimeout(queueTimer);try{updateQueue(await client.cancelMatchmaking(queue.ticket,queue.mode));}catch(e){updateQueue(queue);throw e;}}));
 clearTimeout(queueTimer);const epoch=queueEpoch;queueTimer=setTimeout(async()=>{try{const result=await client.heartbeatMatchmaking(queue.ticket,queue.mode);if(epoch===queueEpoch)updateQueue(result);}catch(e){if(epoch===queueEpoch){feedback(e.message+'，正在重连…',true);queueTimer=setTimeout(()=>{if(epoch===queueEpoch)updateQueue(queue);},2000);}}},Math.min(4500,Math.max(250,10000-queue.elapsed_ms)));}
function render(){if(revealCurrent)return;if(!room)return home();main.onclick=null;$('game-shell').classList.toggle('spectating',!!room.state.spectator);$('game-shell').classList.toggle('preparing',!room.state.spectator&&['choose_first','mulligan'].includes(room.state.phase));$('game-shell').classList.toggle('battle',!['waiting','choose_first','mulligan'].includes(room.state.phase));syncChannel();const s=room.state,you=s.seat,me=s.players[you];if(selection&&!me.hand?.some(c=>c.id===selection))selection=null;
 if(s.spectator){battle();}
 else if(s.phase==='waiting'){$('game-shell').classList.remove('battle');main.innerHTML=`<div class="room-bar"><div><small>邀请朋友加入</small><strong id="room-code">${esc(room.code)}</strong></div><div class="actions">${!s.players[1]?button('发布到公共频道','publish-room','secondary'):''}${button('离开房间','leave','secondary')}</div></div><div class="players">${s.players.map((p,i)=>`<section class="player-panel" data-player="${i}">${p&&i===you?`<img class="room-leader" src="${esc(data.cards[p.selection.leader].art)}" alt="">`: '<span class="hidden-army">◇</span>'}${p?`${identity(p,i===you)}<p class="eyebrow">${p.locked?'军团已锁定':'正在整备'}</p><h2>${i===you?esc(data.factions[p.selection.faction]):'阵营待揭晓'}</h2><p>${i===you?esc(data.cards[p.selection.leader].name):'双方锁定后，同时公开阵营与领袖'}</p>${i===you&&!p.locked?button('更换牌组','room-deck','secondary'):''}`:'<h2>等待来客</h2><p>分享上方房间码，邀请对手加入。</p>'}</section>`).join('')}</div><div class="room-actions">${button(me.locked?'解锁牌组':'锁定牌组','lock-deck')}<p>双方锁定后自动进入换牌阶段</p></div>`;bind('publish-room',()=>run(async()=>{await client.channelChallenge(room.room_id);feedback('约战已发布到公共频道');render();}));bind('leave',()=>run(()=>act('leave')));bind('room-deck',deckPicker);bind('lock-deck',()=>run(()=>act(me.locked?'unlock':'lock')));}
 else if(s.phase==='choose_first'){main.innerHTML=`<section class="match-panel"><p class="eyebrow">寒霜盟约 · 先手选择</p><h2>${s.chooser===you?'谁先踏入战场？':'对手正在选择先手'}</h2>${openingLeaders()}${s.chooser===you?button('我先行动','first-self')+button('对手先行动','first-other','secondary'):''}</section>`;bind('first-self',()=>run(()=>act('first',{seat:you})));bind('first-other',()=>run(()=>act('first',{seat:1-you})));}
 else if(s.phase==='mulligan'){
  for(const id of picks)if(me.mulligan_done||!me.hand.some(c=>c.id===id))picks.delete(id);
  const picked=me.hand.filter(c=>picks.has(c.id));
  main.innerHTML=`<section class="prep"><p class="eyebrow">PREPARE YOUR HAND</p><h2>${me.mulligan_done?'等待对手完成换牌':'选择最多两张手牌替换'}</h2><p class="muted">点选要换掉的牌，再点一次取消。起手7张，第二与第三局各抽2张。</p>${openingLeaders()}<div class="hand">${me.hand.map(c=>card(c,`data-pick="${c.id}" aria-pressed="${picks.has(c.id)}" ${me.mulligan_done?'disabled':''}`,picks.has(c.id))).join('')}</div><div class="mulligan-actions"><p id="mulligan-selection" role="status" aria-live="polite">${me.mulligan_done?'已确认换牌':`<b>已选 ${picked.length}/2</b> · ${picked.length?picked.map(c=>esc(cardData(c).name)).join('、'):'未选中，保留全部手牌'}`}</p>${!me.mulligan_done?button(picked.length?`确认替换 ${picked.length} 张`:'保留全部手牌','confirm-mulligan'):''}</div></section>`;
  document.querySelectorAll('[data-pick]').forEach(n=>n.onclick=()=>{if(me.mulligan_done)return;if(picks.has(n.dataset.pick))picks.delete(n.dataset.pick);else if(picks.size<2)picks.add(n.dataset.pick);else{$('mulligan-selection').textContent='最多替换2张，请先点击已选牌取消';return;}render();});
  bind('confirm-mulligan',()=>run(async()=>{await act('mulligan',{cards:[...picks]});picks.clear();}));
 }
 else battle();if($('modal').open&&$('modal').dataset.view?.startsWith('leader-'))inspectLeader(Number($('modal').dataset.leaderSeat),$('modal').dataset.view==='leader-confirm');images();tick();if(s.pending?.options)requestAnimationFrame(()=>document.querySelector('.choice-panel')?.scrollIntoView({block:'nearest'}));}
function battleMarkup(s,selection=null,playSelection=false,pickedOption=null){
 const you=s.seat,me=s.players[you],enemy=s.players[1-you],moves=s.legal_moves||[],chosen=me.hand?.find(c=>c.id===selection),available=moves.filter(m=>m.action==='play'&&m.payload.card===selection),isStory=s.mode==='story',isExpedition=s.mode==='expedition';
 const targetIds=new Set(s.pending?.multi_select&&!s.tutorial?choiceIds:pickedOption?.target_ids||[]),eligibleTargets=new Set(s.pending?.options?.flatMap(o=>o.target_ids)||[]);
 const panel=(p,i)=>`<aside class="army-summary">${identity(p,i===you)}<div class="score">${p.score}<small>${p.passed?'已停手':'总战力'}</small></div><p class="gems">${'◆'.repeat(s.lives[i])}${'◇'.repeat((isExpedition?1:2)-s.lives[i])}</p><p class="faction-name">${emblem(p.faction)}${esc(factionName(p.faction))}</p>${p.leader?`<button class="leader-inspect secondary" data-battle-leader="${i}" aria-label="查看${i===you?'己方':'对手'}领袖技能"><b>${esc(data.cards[p.leader].name)}</b><small>${leaderStatus(p)} · 查看技能</small></button>`:'<p class="muted">无领袖 · 单局定胜负</p>'}<p class="muted">手牌 ${p.hand_count} · 牌库 ${p.deck_count}</p>${p.passed?'<b class="passed">已停手</b>':''}<button data-grave="${i}" class="secondary grave-button" aria-label="查看${i===you?'己方':'对手'}弃牌堆，共${p.discard.length}张"><b>弃牌堆 ${p.discard.length}</b><span>查看 ›</span></button></aside>`;
 const lane=(p,i,r)=>{const destination=chosen&&cardData(chosen).abilities.includes('spy')?1-you:you;const playable=playSelection&&i===destination&&available.some(m=>m.payload.row===r);return `<div class="combat-row ${playable?'eligible':''}" data-row="${r}" data-seat="${i}"><div class="row-title"><img src="../assets/classic/ui/row-${['melee','ranged','siege'][r]}.svg" alt=""><span>${rows[r]}</span><b>${p.row_scores[r]}</b><small>${p.rows[r].length}/4</small></div><div class="row-slots">${Array.from({length:4},(_,slot)=>p.rows[r][slot]?`<div class="unit-slot occupied ${targetIds.has(p.rows[r][slot].id)?'target-preview':eligibleTargets.has(p.rows[r][slot].id)?'target-available':''}">${card(p.rows[r][slot],`data-inspect="${p.rows[r][slot].id}" aria-label="${esc(cardData(p.rows[r][slot]).name)} · 当前战力 ${p.rows[r][slot].power} · 查看效果"`)}<small class="unit-status">${p.rows[r][slot].power_detail.shield?'盾 '+p.rows[r][slot].power_detail.shield:''}${shortStatus(p.rows[r][slot])}</small></div>`:`<div class="unit-slot empty-slot"><span>${playable?'部署':'◇'}</span></div>`).join('')}</div></div>`;};
 const spells=(p)=>`<div class="spell-slots" aria-label="持续术区">${Array.from({length:3},(_,i)=>p.spells[i]?`<button class="${targetIds.has(p.spells[i].id)?'target-preview':eligibleTargets.has(p.spells[i].id)?'target-available':''}" data-spell="${p.spells[i].id}" aria-label="${esc(cardData(p.spells[i]).name)} · 点击查看效果"><img src="${esc(cardData(p.spells[i]).art)}" alt=""><b>${esc(cardData(p.spells[i]).name)}</b><small>${shortStatus(p.spells[i])||(p.spells[i].row>=0?rows[p.spells[i].row]:'持续生效')}</small></button>`:`<div class="empty-spell">持续术位 ${i+1}</div>`).join('')}</div>`;

 return `<div class="battle-top"><div><p class="eyebrow">${s.tutorial?'新手教学 · 固定演练':s.spectator?'好友观战 · 公开战场':isStory?`STORY · 第 ${s.story.chapter} 章 · ${esc(s.story.title)}`:s.ranked?`S${s.ranked.season_id} · 排位赛`:isExpedition?'远征 · 三族试炼':'V3 · FOUR SLOTS PER ROW'}</p><b>第 ${s.round} 局</b></div><strong id="battle-status" role="status" aria-live="polite">${esc(battleStatus(s,{reconnecting:connectionLost,animating:!!revealCurrent||effectFeedback.active,submitting:busy}))}</strong><span id="countdown"></span>${button('记录','view-log','secondary')}</div><section class="army enemy">${panel(enemy,1-you)}<div class="lanes">${spells(enemy)}${[2,1,0].map(r=>lane(enemy,1-you,r)).join('')}</div></section><div class="battle-divider"><span>◇</span> 每排4位 · 战力归零即阵亡 <span>◇</span></div><section class="army self">${panel(me,you)}<div class="lanes">${[0,1,2].map(r=>lane(me,you,r)).join('')}${spells(me)}</div></section><section class="hand-area" ${s.spectator?'hidden':''}>${chosen&&!playSelection?`<aside class="hand-preview" aria-label="所选手牌效果"><button id="dismiss-hand" aria-label="收起手牌说明">×</button><b>${esc(cardData(chosen).name)}</b>${cardData(chosen).type==='unit'?`<span class="hand-card-rows">可部署：${esc(cardData(chosen).rows.map(r=>rows[r]).join(' / '))}</span>`:''}${statusTags(chosen)}<p>${esc(desc(cardData(chosen))||'依靠基础战力争夺本局优势。')}</p><small>${available.length?'点击「使用」后出牌；需要目标时再选择目标。':esc(chosen.unavailable_reason||'当前不可使用，可继续查看卡牌。')}</small></aside>`:''}<div class="hand-label"><b>你的手牌 · ${me.hand_count}</b><span>点击手牌查看或使用 · 左右滑动浏览</span></div><div class="hand">${(me.hand||[]).map(c=>`<div class="hand-card ${selection===c.id?'active':''}">${card(c,`data-hand="${c.id}" aria-pressed="${selection===c.id}"`,selection===c.id)}${selection===c.id?`<div class="hand-actions">${button('查看','inspect-hand','secondary')}<button id="use-hand" ${available.length?'':'disabled'}>使用</button></div>`:''}</div>`).join('')}</div></section>${s.spectator?'':rankResult(s)}<div class="controls">${s.spectator?`<div class="selection-info"><strong>正在观战 · ${esc(me.name)}</strong><p>双方手牌与选牌内容不可见 · 点击场上卡牌查看效果</p></div>${button('退出观战','exit-spectate','secondary')}`:`<div class="selection-info"><strong>${chosen?(playSelection?'请选择高亮战列 · ':!available.length?'当前不可使用 · ':'已选 · ')+esc(cardData(chosen).name):isExpedition?'单局定胜负 · 战后重新洗牌': '以少胜多，为下一局留牌'}</strong><p>${chosen?esc(desc(cardData(chosen)))+(!available.length?' · '+esc(chosen.unavailable_reason||'当前无法使用'):''):'双方停手后结算本局；停手后本局不能再次行动。'}</p></div>${isExpedition&&s.phase!=='finished'?button('暂离远征','pause-expedition','secondary'):''}${moves.some(m=>m.action==='leader')?button('领袖能力','use-leader','secondary'):''}${moves.some(m=>m.action==='pass')?button('本局停手','pass'):''}${s.phase==='finished'?(isExpedition?button(s.winner===you?'领取远征奖励':'查看远征结果','leave'):isStory?button('返回章节','leave','secondary'):(s.ranked||s.tutorial?'':moves.some(m=>m.action==='rematch')?button('再战一局','rematch'):'<span>等待对手再战</span>')+button('返回大厅','leave','secondary')):button('认输','concede','secondary')}`}</div>${s.events?.length?`<div class="battle-log" aria-live="polite">${s.events.map(esc).join(' · ')}</div>`:''}${s.pending?.options&&!s.tutorial?choicePanel(s.pending,pickedOption):''}`;

}
function battle(){$('game-shell').classList.add('battle');const handScroll=document.querySelector('.hand-area .hand')?.scrollLeft||0;const s=room.state,you=s.seat,me=s.players[you],moves=s.legal_moves||[],chosen=me.hand?.find(c=>c.id===selection),available=moves.filter(m=>m.action==='play'&&m.payload.card===selection);
 const pendingKey=s.pending?.options?`${room.match_id}:${s.version}`:'';if(pendingKey!==choiceKey){choiceKey=pendingKey;choiceIds=[];choiceSelection=null;choiceTarget=null;choiceCollapsed=false;choiceNotice='';}
 const pickedOption=s.pending?.options?.find(o=>o.token===choiceSelection);
 main.innerHTML=battleMarkup(s,selection,playSelection,pickedOption);
 document.querySelectorAll('[data-battle-leader]').forEach(n=>n.onclick=()=>inspectLeader(Number(n.dataset.battleLeader)));
 document.querySelectorAll('[data-hand]').forEach(n=>n.onclick=()=>{selection=selection===n.dataset.hand?null:n.dataset.hand;playSelection=false;render();});
 document.querySelectorAll('.eligible').forEach(n=>n.onclick=e=>{if(e.target.closest('[data-inspect]'))return;run(()=>act('play',{card:selection,row:Number(n.dataset.row)}));});
 document.querySelectorAll('[data-option]').forEach(n=>n.onclick=()=>{const top=document.querySelector('.target-options').scrollTop;choiceSelection=n.dataset.option;choiceNotice='';render();document.querySelector('.target-options').scrollTop=top;});
 document.querySelectorAll('[data-choice-card]').forEach(n=>n.onclick=()=>toggleChoiceCard(n.dataset.choiceCard));
 bind('choice-board',()=>{choiceCollapsed=!choiceCollapsed;render();});bind('choice-all',()=>{choiceTarget=null;choiceNotice='';render();});
 bind('skip-multi-choice',()=>{const skip=s.pending.options.find(o=>o.select_ids?.length===0);if(skip){choiceIds=[];choiceSelection=skip.token;choiceNotice='已选择跳过，请确认';render();}});
 bind('confirm-choice',()=>{if(choiceSelection!==null)run(()=>act('choose',{option:choiceSelection}));});
 document.querySelectorAll('[data-inspect]').forEach(n=>n.onclick=()=>chooseBoardTarget(n.dataset.inspect)||inspectCard(s.players.flatMap(p=>p.rows.flat()).find(c=>c.id===n.dataset.inspect)));
 document.querySelectorAll('[data-spell]').forEach(n=>n.onclick=()=>chooseBoardTarget(n.dataset.spell)||inspectCard(s.players.flatMap(p=>p.spells).find(c=>c.id===n.dataset.spell)));
 document.querySelectorAll('[data-grave]').forEach(n=>n.onclick=()=>inspectGrave(Number(n.dataset.grave)));
 document.querySelector('.hand-area .hand').scrollLeft=handScroll;
 bind('inspect-hand',()=>inspectCard(chosen));
 const dismissHand=()=>{selection=null;playSelection=false;render();};
 bind('dismiss-hand',dismissHand);
 main.onclick=e=>{if(chosen&&!playSelection&&!e.target.closest('button,input,a,.hand-preview,.choice-panel'))dismissHand();};
 bind('use-hand',()=>{if(!available.length)return;if(available.length===1)run(()=>act('play',available[0].payload));else{playSelection=true;render();}});
 bind('pause-expedition',()=>{closeExpeditionBattle();home();});
 bind('view-log',()=>{matchLogAll=false;showMatchLog();});bind('exit-spectate',leaveSpectate);
 bind('use-leader',()=>inspectLeader(you,true));bind('pass',confirmPass);bind('rematch',()=>run(()=>act('rematch')));bind('leave',()=>run(()=>act('leave')));
 bind('concede',()=>modal(`<h2>结束这场对局？</h2><p>认输后对手赢得本场对局。</p>${button('确认认输','confirm-concede')}`));
 if($('concede'))$('concede').addEventListener('click',()=>bind('confirm-concede',()=>run(async()=>{$('modal').close();await act('concede');})));
}
function chooseBoardTarget(id){
 const pending=room.state.pending;if(!pending?.options)return false;
 if(pending.multi_select){toggleChoiceCard(id);return true;}
 const options=pending.options.filter(o=>o.target_ids.includes(id));
 choiceNotice='';
 if(!options.length){choiceSelection=null;choiceNotice=pending.target_reasons?.[id]||'此牌不符合当前效果的目标条件';render();return true;}
 choiceTarget=id;
 if(options.length===1){choiceSelection=options[0].token;choiceCollapsed=true;}
 else{choiceSelection=null;choiceCollapsed=false;choiceNotice='已定位此单位，请选择目标组合或移动目的战列';}
 render();return true;
}
function toggleChoiceCard(id){
 const pending=room.state.pending,top=document.querySelector('.target-options')?.scrollTop||0;
 const next=toggleSelection(pending,choiceIds,id);choiceIds=next.ids;choiceNotice=next.notice;
 choiceSelection=selectionOption(pending,choiceIds)?.token??null;
 render();const list=document.querySelector('.target-options');if(list)list.scrollTop=top;
}
function multiChoicePanel(pending,picked,ids,collapsed,notice){
 const m=pending.multi_select,skip=pending.options.find(o=>o.select_ids?.length===0);
 return `<section class="choice-panel ${collapsed?'choice-collapsed':''}"><div class="choice-heading"><p class="eyebrow">${esc(pending.prompt)} · ${m.minimum===m.maximum?'选择'+m.maximum+'张':'至多'+m.maximum+'张'}</p><button id="choice-board">${collapsed?'展开卡牌':'收起列表 · 点战场'}</button></div><small class="choice-help">${esc(notice||'点击卡牌勾选，再点一次取消；确认后才生效'+(m.ordered?'，按选择顺序结算':''))}</small>${collapsed?'':`<div class="target-options multi-target-options">${m.cards.map(t=>`<button data-choice-card="${esc(t.id)}" aria-pressed="${ids.includes(t.id)}"><img src="${esc(cardData(t.card).art)}" alt=""><span class="choice-content"><span class="choice-markers"><span class="choice-side" data-side="${esc(t.side)}">${t.side==='own'?'己方':'敌方'}</span><span class="choice-selected">✓ 已选 ${ids.indexOf(t.id)+1}</span></span><b>${esc(t.label)}</b><small>${esc(t.row!==undefined?rows[t.row]:t.zone)}${t.power!==undefined?' · 战力'+esc(t.power):''}</small></span></button>`).join('')}</div>`}${picked?.preview?.length?`<div class="choice-preview" role="status">${picked.preview.map(esc).join('；')}<small>${esc(picked.preview_note)}</small></div>`:''}<div class="choice-footer"><span role="status">已选 ${ids.length}/${m.maximum}${ids.length?' · '+ids.map(id=>esc(m.cards.find(c=>c.id===id).label)).join('、'):''}</span>${skip?`<button id="skip-multi-choice">跳过</button>`:''}<button id="confirm-choice" ${picked?'':'disabled'}>确认选择</button></div></section>`;
}
function choicePanel(pending,picked,{selected=choiceSelection,target=choiceTarget,collapsed=choiceCollapsed,notice=choiceNotice,ids=choiceIds}={}){
 if(pending.multi_select&&ids!==null)return multiChoicePanel(pending,picked,ids,collapsed,notice);
 const options=target?pending.options.filter(o=>o.target_ids.includes(target)):pending.options;
 return `<section class="choice-panel ${collapsed?'choice-collapsed':''}"><div class="choice-heading"><p class="eyebrow">${esc(pending.prompt||pending.title)}</p><button id="choice-board">${collapsed?'展开选项':'收起列表 · 点战场'}</button>${target?'<button id="choice-all">全部选项</button>':''}</div><small class="choice-help">${notice?esc(notice):collapsed?'点击场上单位或持续术选择目标；确认后生效':`${options.length} 个选项 · 点选预览，确认后生效`}</small>${collapsed?'':`<div class="target-options">${options.map(o=>{
  const targets=o.target_sides||[],mixed=new Set(targets.map(t=>t.side)).size>1,markers=mixed?targets:targets.slice(0,1);
  return `<button data-option="${esc(o.token)}" aria-pressed="${selected===o.token}">${o.card?`<img src="${esc(cardData(o.card).art)}" alt="">`:''}<span class="choice-content"><span class="choice-markers">${markers.map(t=>`<span class="choice-side" data-side="${esc(t.side)}">${t.side==='own'?'己方':'敌方'}${mixed?' · '+esc(t.label):''}</span>`).join('')}<span class="choice-selected">✓ 已选择</span></span>${esc(o.label)}${targets.length?`<small>${targets.map(t=>esc(`${t.label} · ${t.row!==undefined?rows[t.row]:t.zone||''}${t.power!==undefined?' · 战力'+t.power:''}`)).join('<br>')}</small>`:''}${o.effect_hint?`<small class="choice-effect">${esc(o.effect_hint)}</small>`:''}</span></button>`;
 }).join('')}</div>`}${picked?.preview?.length?`<div class="choice-preview" role="status">${picked.preview.map(esc).join('；')}<small>${esc(picked.preview_note)}</small></div>`:''}<div class="choice-footer"><span role="status">${picked?'✓ '+esc(picked.selection_hint||'已选择')+' · '+esc(picked.label):'尚未选择目标'}</span><button id="confirm-choice" ${picked?'':'disabled'}>确认${picked?.label==='跳过'?'跳过':'选择'}</button></div></section>`;
}
function inspectGrave(seat,page=0){
 const cards=room.state.players[seat].discard,pageSize=6,pages=Math.max(1,Math.ceil(cards.length/pageSize));
 page=Math.max(0,Math.min(page,pages-1));
 modal(`<section class="grave-view"><h2>${seat===room.state.seat?(room.state.spectator?'好友':'己方'):'对手'}弃牌堆 · ${cards.length} 张</h2><p>这里存放已弃置或离场的卡牌。点击卡牌查看效果；符合条件的卡牌可被复活或回收。</p><div class="grave-grid">${cards.slice(page*pageSize,(page+1)*pageSize).map((c,i)=>card(c,`data-grave-card="${page*pageSize+i}" aria-label="查看${esc(cardData(c).name)}效果"`)).join('')||'<p class="grave-empty">暂无弃牌，离场的卡牌会显示在这里。</p>'}</div>${pages>1?`<nav class="card-pagination"><button id="grave-prev" ${page===0?'disabled':''}>上一页</button><span>${page+1} / ${pages}</span><button id="grave-next" ${page===pages-1?'disabled':''}>下一页</button></nav>`:''}</section>`,'grave');
 bind('grave-prev',()=>inspectGrave(seat,page-1));bind('grave-next',()=>inspectGrave(seat,page+1));
 document.querySelectorAll('[data-grave-card]').forEach(n=>n.onclick=()=>{
  const chosen=cards[Number(n.dataset.graveCard)];inspectCard(chosen);
  const reason=room.state.pending?.target_reasons?.[chosen.id];if(reason)$('modal-content').insertAdjacentHTML('beforeend',`<p class="target-reason">不可选：${esc(reason)}</p>`);
  $('modal-content').insertAdjacentHTML('beforeend',button('返回弃牌堆','back-grave','secondary'));
  bind('back-grave',()=>inspectGrave(seat,page));
 });
}
function clearReveal(){
 effectFeedback.clear();
 clearTimeout(revealTimer);revealTimer=null;revealQueue=[];revealCurrent=null;main.inert=false;
 $('action-reveal').hidden=true;$('action-reveal-content').innerHTML='';
}
function syncActionLog(previous,value){
 const sameMatch=previous?.room_id===value.room_id&&previous.match_id===value.match_id&&value.state.phase!=='waiting';
 if(!sameMatch){clearReveal();room=value;render();return;}
 if(value.state.turn===value.state.seat&&previous.state.turn!==value.state.turn&&!value.state.pending)gameAudio.play('turn');
 if(!gameSettings.animations){clearReveal();room=value;render();return;}
 const frames=(value.state.action_frames||[]).filter(f=>f.version>previous.state.version);
 for(const frame of frames)revealQueue.push({frame,value,event:value.state.action_log.find(e=>e.id===frame.event_id)});
 if(!revealCurrent&&!effectFeedback.active)nextReveal();
 updateBattleStatus();
}
function applyRevealFrame(item){
 const {frame,value}=item,hand=room.state.players[room.state.seat].hand||[];
 room={...value,state:{...value.state,...frame.state,version:frame.version,pending:null,legal_moves:[],action_log:value.state.action_log.filter(e=>e.id<=frame.log_id),
  players:value.state.players.map((p,i)=>({...p,...frame.state.players[i],...(i===value.state.seat?{hand:hand.filter(c=>c.id!==frame.played)}:{})}))}};
 render();
}
function applyEffectFrame(item){
 const oldCards=effectFeedback.snapshot();applyRevealFrame(item);$('action-reveal').hidden=true;
 if(effectFeedback.play(item.frame.effects,oldCards,nextReveal)){main.inert=true;updateBattleStatus();return true;}
 return false;
}
function nextReveal(){
 if(effectFeedback.active){effectFeedback.skip();return;}
 clearTimeout(revealTimer);revealTimer=null;
 if(revealCurrent){const done=revealCurrent;revealCurrent=null;if(applyEffectFrame(done))return;}
 while(revealQueue.length){
  const item=revealQueue.shift(),event=item.event,d=event&&cardData(event.card||'');
  if(!d){if(applyEffectFrame(item))return;continue;}
  gameAudio.play('card');revealCurrent=item;main.inert=true;updateBattleStatus();
  const actor=item.value.state.players[event.seat],self=event.seat===item.value.state.seat;
  // Remove the used hand card before the reveal, without exposing the resulting board yet.
  const handNode=self&&item.frame.played?[...document.querySelectorAll('[data-hand]')].find(n=>n.dataset.hand===item.frame.played):null;
  if(handNode)handNode.closest('.hand-card').style.visibility='hidden';
  $('action-reveal').dataset.side=self?'self':'enemy';$('action-reveal').dataset.kind=event.kind;
  $('action-reveal-content').innerHTML=`<div class="reveal-stage"><div class="reveal-art ${event.kind==='leader'?'reveal-leader':''}"><img src="${esc(d.art)}" alt="${esc(d.name)}"></div><div class="reveal-copy"><p class="eyebrow">${item.value.state.spectator?esc(actor.name||'旅人'):self?'己方':'对手'} · ${event.kind==='leader'?'领袖技能':'使用卡牌'}</p><small>${esc(actor.name||'旅人')}</small><h2>${esc(d.name)}</h2><p>${esc(desc(d))}</p></div></div>`;
  $('action-reveal').hidden=false;
  const art=document.querySelector('#action-reveal .reveal-art'),army=self?'self':'enemy';
  const origin=event.kind==='leader'?document.querySelector(`.army.${army} .leader-inspect`):handNode||document.querySelector(`.army.${army} .identity`);
  if(art&&origin&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches)art.animate([{transform:revealTravel(art,origin),opacity:.3},{transform:'translate(0,0) scale(1)',opacity:1}],{duration:220,easing:'ease-out'});
  revealTimer=setTimeout(landReveal,revealQueue.length?(event.kind==='leader'?800:500):(event.kind==='leader'?1100:850));return;
 }
 $('action-reveal').hidden=true;main.inert=false;
 if(latestRoom){room=latestRoom;render();}
 if($('modal').open&&$('modal').dataset.view==='match-log'){const scroll=$('match-log-list')?.scrollTop||0;showMatchLog();$('match-log-list').scrollTop=scroll;}
}
function revealTravel(art,target){
 const from=art.getBoundingClientRect(),to=target.getBoundingClientRect(),shell=$('game-shell').getBoundingClientRect();
 // Convert screen distances back into the rotated/scaled game's local coordinates.
 const rotated=document.documentElement.classList.contains('screen-rotated'),scale=(rotated?shell.height:shell.width)/$('game-shell').offsetWidth;
 const x=(to.x+to.width/2-from.x-from.width/2)/scale,y=(to.y+to.height/2-from.y-from.height/2)/scale;
 const dx=rotated?y:x,dy=rotated?-x:y,size=Math.min(1,to.width/from.width,to.height/from.height);
 return `translate(${dx}px,${dy}px) scale(${size})`;
}
function landReveal(){
 if(!revealCurrent)return;
 const landing=revealCurrent.frame.landing,art=document.querySelector('#action-reveal .reveal-art'),stage=document.querySelector('#action-reveal .reveal-stage');
 let target;
 if(landing){
  const army=landing.seat===room.state.seat?'self':'enemy';
  target=landing.row===-1?document.querySelectorAll(`.army.${army} .spell-slots>*`)[landing.slot]:document.querySelectorAll(`.combat-row[data-seat="${landing.seat}"][data-row="${landing.row}"] .unit-slot`)[landing.slot];
 }
 if(target&&art){
  const travel=window.matchMedia('(prefers-reduced-motion: reduce)').matches?'none':revealTravel(art,target);
  art.animate([{transform:'translate(0,0) scale(1)',opacity:1},{transform:travel,opacity:0}],{duration:300,easing:'ease-in',fill:'forwards'});
  stage.querySelector('.reveal-copy').animate([{opacity:1},{opacity:0}],{duration:200,fill:'forwards'});
 }else if(stage)stage.animate([{opacity:1},{opacity:0}],{duration:300,fill:'forwards'});
 revealTimer=setTimeout(nextReveal,300);
}
function updateBattleStatus(){const node=$('battle-status');if(node&&room)node.textContent=(recoveredVersion===room.state.version&&!connectionLost?'已同步 · ':'')+battleStatus(room.state,{reconnecting:connectionLost,animating:!!revealCurrent||effectFeedback.active,submitting:busy});}
function showMatchLog(){
 const s=room.state,actions=groupMatchActions(s.action_log||[],s.action_frames||[]),visible=matchLogAll?actions:actions.slice(-6);
 const opened=new Set([...document.querySelectorAll('#match-log-list details[open]')].map(n=>n.dataset.action)),rounds=[...new Set(visible.map(e=>e.round))].reverse();
 const actor=e=>e.seat===null?'':`${e.seat===s.seat?(s.spectator?'好友':'你'):'对手'} · ${s.players[e.seat]?.name||'旅人'}`;
 modal(`<section class="match-history"><p class="eyebrow">MATCH HISTORY</p><h2>对局战报</h2><div class="log-toolbar"><span>${matchLogAll?'整场行动':'最近6次行动'} · 最新在前</span><button id="toggle-full-log" class="secondary">${matchLogAll?'只看最近':'展开整场'}</button></div><div id="match-log-list">${rounds.map(round=>`<section class="log-round"><h3>第 ${round} 局</h3>${visible.filter(e=>e.round===round).reverse().map(e=>`<details data-action="${e.id}" ${opened.has(String(e.id))||e.id===actions.at(-1)?.id?'open':''}><summary><small>${esc(actor(e))}</small><b>${esc(e.text)}</b><span>查看结算</span></summary><ol>${e.steps.map(step=>`<li>${step.kind==='choose'?'<small>后续效果选择</small>':''}${(step.effects||[]).map(cue=>`<p>${esc(stepText(cue,id=>cardData(id)?.name||'卡牌',s.seat))}</p>`).join('')}${(step.details||[]).map(text=>`<p class="log-detail">${esc(text)}</p>`).join('')||(!(step.effects||[]).length?'<p class="log-detail">'+esc(step.kind==='round_end'?'比分按房主 / 来客排列':step.kind==='round_start'?'本小局开始':step.kind==='pass'?'停手后本小局不再行动':'本次行动无额外公开结算记录')+'</p>':'')}</li>`).join('')}</ol></details>`).join('')}</section>`).join('')||'<p>暂无对局记录；旧版本未记录的效果无法补记。</p>'}</div></section>`,'match-log');
 bind('toggle-full-log',()=>{matchLogAll=!matchLogAll;showMatchLog();});
}

function confirmPass(){
 modal(`<section class="pass-confirm"><p class="eyebrow">结束本局行动</p><h2>确定本局停手？</h2><p>停手后，本局不能再出牌或使用领袖能力。<br>对手仍可继续出牌，直到也选择停手。</p><p class="muted">${room.state.mode==='expedition'?'远征本场只打一局；胜利后，下场战斗重洗整副牌组并抽5张。':'剩余手牌会保留到下一局。'}</p><div class="actions">${button('继续出牌','cancel-pass','secondary')}${button('确认停手','confirm-pass')}</div></section>`,'pass-confirm');
 bind('cancel-pass',()=>$('modal').close());
 bind('confirm-pass',()=>run(async()=>{$('modal').close();await act('pass');}));
 $('cancel-pass').focus();
}
function tick(){if(queue&&$('elapsed'))$('elapsed').textContent=Math.floor(((queue.elapsed_ms||0)+performance.now()-queue.receivedAt)/1000);if(room&&$('countdown')){const n=remainingSeconds(room.state,receivedAt);$('countdown').textContent=n===null?'':n+' 秒';}}
async function boot(){profile=await client.boot();gameSettings={...gameSettings,...profile.settings};syncChannel();if(profile.matchmaking?.status==='waiting'&&profile.matchmaking.rules_version!==3){location.replace((profile.matchmaking.rules_version===2?'../classic/':'../')+location.search+location.hash);return;}[data,tutorialScenes]=await Promise.all(['./cards.json','./tutorial.json'].map(async url=>(await fetch(url)).json()));let saved=await client.decks();decks=saved.decks;if(!decks.length){for(const d of data.starters)await client.saveDeck(d);saved=await client.decks();decks=saved.decks;saved=await client.selectDeck(decks[0].id);}selectedDeck=saved.selected_deck_id||decks[0].id;client.sdk?.loading?.ready?.();if(profile.room_id)enter(await client.snapshot(profile.room_id));else if(profile.matchmaking?.status==='waiting'&&profile.matchmaking.rules_version===3){queueEpoch++;updateQueue(profile.matchmaking);}else {home();tutorial.offer();}void social.start();}
bind('skip-reveal',nextReveal);$('action-reveal').onclick=e=>{if(e.target.id!=='skip-reveal')nextReveal();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('action-reveal').hidden&&!$('modal').open){e.preventDefault();nextReveal();}});
function closeModal(){
 const view=$('modal').dataset.view;
 if(deckSaving&&['builder','card-editor','builder-filters'].includes(view))return;
 if(view==='builder-filters'){builderView();return;}
 if(['builder','card-editor'].includes(view)&&deckChanged(draft,builderOriginal)){
  modal(`<h2>牌组还有未保存修改</h2><p>离开将放弃本次修改，原牌组保持不变。</p><div class="actions">${button('继续编辑','keep-editing')}${button('放弃修改','discard-edit','secondary')}</div>`,'unsaved-deck');
  bind('keep-editing',builderView);bind('discard-edit',()=>{draft=structuredClone(builderOriginal);$('modal').close();});return;
 }
 if(view==='unsaved-deck'){builderView();return;}
 $('modal').close();
}
$('modal').addEventListener('cancel',e=>{if(['builder','card-editor','builder-filters','unsaved-deck'].includes($('modal').dataset.view)){e.preventDefault();closeModal();}});
addEventListener('beforeunload',e=>{if($('modal').open&&['builder','card-editor','builder-filters','unsaved-deck'].includes($('modal').dataset.view)&&deckChanged(draft,builderOriginal)){e.preventDefault();e.returnValue='';}});
bind('close-modal',closeModal);bind('home',e=>{e.preventDefault();if(tutorial.active())tutorial.exit();else if(!room&&!queue)home();});bind('reconnect',()=>run(async()=>{if(tutorial.active()){feedback('教学为本地演练，无需重新连接');return;}if(room?.state.mode==='expedition')await expedition.open();else if(room)accept(await client.snapshot());else await boot();}));
$('modal').addEventListener('close',syncChannel);
bind('channel-toggle',()=>toggleChannel(!channelOpen));bind('channel-close',()=>toggleChannel(false));
bind('channel-challenge',()=>run(async()=>publishChallenge(await client.create(selected().id))));
function sendChannel(){const input=$('channel-input'),text=input.value.trim();if(!text)return;run(async()=>{await client.channelPost(text);input.value='';});}
bind('channel-send',sendChannel);$('channel-input').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();sendChannel();}};
setupScreen();
bind('rules',()=>modal(`<h2>四格战阵 · 第三版</h2><div class="rule-text"><p>每方两点生命，小局败者失去一点，平局双方各失去一点。最多三小局，手牌跨局保留。</p><p>牌组恰好20张，至少14张单位（含最多2张英雄），术卡最多6张。起手7张，最多换2张；第二和第三局各抽2张。</p><p>每次行动出一张牌、使用领袖或停手。三排各4个单位位，满排不能部署；召集只拉牌库中的牌，受空位限制。间谍占对方一格，整场每张只抽牌一次。</p><p>战力 = 基础 + 强化 + 条件 − 伤害，归零即死亡。强化可以累加，条件战力单独计算。英雄可受伤、被封印，条件随场面实时变化；英雄和间谍不能复活。</p><p>每方有3个持续术位，即时术结算后弃置。术位满时不能再打持续术。号角、鼓舞及旧阵营免费被动已移除。</p></div>`));
const social=setupSocial({client,spectate,showProfile:uid=>personal.open(uid),onChannel:value=>{channelItems=client.acceptChannel(value).items;renderChannel();},ready:()=>!!profile&&!!selected(),currentRoom:()=>room?.room_id,isBusy:()=>!!room||!!queue||tutorial.active(),deck:selected,enter:value=>{if($('modal').open)$('modal').close();enter(value);},openChannel:toggleChannel});
const tutorial=setupTutorial({cards:()=>data,scenes:()=>tutorialScenes,view:battleMarkup,choices:choicePanel,card,inspect:inspectCard,uid:()=>profile?.uid,eligible:()=>profile?.has_played===false,blocked:()=>!selected()||!!room||!!queue,home,modal,closeModal:()=>$('modal').close(),sync:syncChannel});
const ranked=setupRanked({client,main,uid:()=>profile?.uid,deck:selected,home,start:startQueue,run,images,onHonor:value=>profile.honor=value});
addEventListener('offline',()=>{if(room){connectionLost=true;updateBattleStatus();}});
const personal=setupProfile({client,uid:()=>profile?.uid,modal,cards:()=>data,onSettings:value=>{gameSettings=value;if(!value.animations&&room&&latestRoom){clearReveal();room=latestRoom;render();}},onHonor:value=>{profile.honor=value;},playTutorial:()=>tutorial.start(),isBusy:()=>!!room||!!queue||tutorial.active(),deck:selected,spectate,privateChat:p=>social.openPrivate(p)});
setInterval(tick,250);run(boot);
