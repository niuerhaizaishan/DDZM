import {createCanvas} from './canvas.js';
import {createClient} from './client.js';
import {CONFIG} from './config.js';
import {platformLoading} from '../runtime.js';
import {moduleEnvironment} from '../module-document.js';

const environment=moduleEnvironment();
const document=environment.document;
const location=environment.location;

const $=selector=>document.querySelector(selector);
const sdk=window.MoyuClubRuntime?.sdk??window.dzmm;
const loading=platformLoading(sdk);
const client=createClient({sdk,apiBase:CONFIG.apiBase});
let room=null,rooms=[],generation=0,followStop=null,composing=false,readySent=false,roomReceivedAt=0,timer=null;
let currentTool={tool:'pen',color:'#222222',width:0.008};

const board=createCanvas($('#draw-canvas'),{onBatch:async operations=>{
  if(!room)return;
  try{await client.strokes(room.room_id,room.state.turn_id,operations);}
  catch(error){board.setEditable(false);feedback(error.message);}
}});

function feedback(text=''){$('#feedback').textContent=text;}
function show(selector,value=true){$(selector).hidden=!value;}
function phaseText(phase){return {waiting:'候场中',selecting:'选词中',drawing:'作画中',revealing:'答案揭晓',finished:'本局结束',closed:'房间关闭'}[phase]||phase;}
function setRoom(value){room=value;roomReceivedAt=Date.now();}
function secondsLeft(){if(!room?.state.deadline_ms)return null;const now=room.server_time_ms+(Date.now()-roomReceivedAt);return Math.max(0,Math.ceil((room.state.deadline_ms-now)/1000));}
function safeLog(kind,message,data,code){try{sdk?.log?.[kind]?.(message,data,code);}catch{}}
function markReady(){if(!readySent){readySent=true;loading?.ready?.();}}
function clearPrivateRoom(){
  room=null;rooms=[];$('#prompt').textContent='猜猜画的是什么';$('#word-hint').textContent='';
  $('#word-cards').replaceChildren();$('#messages').replaceChildren();$('#reveal').replaceChildren();
  board.restore({turn_id:-1,canvas:[]});renderLobby();
}

async function boot(refresh=false){
  const token=++generation;feedback('正在读取玩家身份…');loading?.progress?.({phase:'runtime_initializing',progress:20,message:'正在进入游戏'});
  followStop?.();followStop=null;clearPrivateRoom();
  try{
    const uid=await client.identity(refresh);if(token!==generation)return;
    feedback('正在获取房间…');rooms=await client.rooms();if(token!==generation)return;
    const activeRooms=rooms.filter(item=>!['finished','closed'].includes(item.phase));
    const linkedRoom=new URLSearchParams(location.search).get('room');
    if(typeof linkedRoom==='string'&&activeRooms.some(item=>item.room_id===linkedRoom)){await enterRoom(linkedRoom,token);return;}
    const stored=await client.kvGet(`drawguess:last-room:${uid}`);if(token!==generation)return;
    const roomId=stored?.value??stored;
    if(typeof roomId==='string'&&activeRooms.some(item=>item.room_id===roomId)){await enterRoom(roomId,token);return;}
    renderLobby();feedback();markReady();
  }catch(error){
    if(token!==generation)return;feedback(error.message||'加载失败，请重试');safeLog('error','你画我猜启动失败',{stage:'boot'},'DRAWGUESS_BOOT_FAILED');loading?.error?.('DRAWGUESS_BOOT_FAILED',error.message||'加载失败');
  }
}

function renderLobby(){
  window.MoyuClubRuntime?.clearRoomContext?.();
  document.body.classList.remove('room-open');setChatOpen(false);show('#lobby');show('#room-view',false);const list=$('#rooms');list.replaceChildren();
  const active=rooms.filter(item=>!['finished','closed'].includes(item.phase));
  if(!active.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='暂无房间，可以先开一局';list.append(empty);return;}
  for(const item of active){
    const button=document.createElement('button');button.type='button';button.className='room-button';
    const title=document.createElement('strong');title.textContent=`${item.creator_name}的房间`;
    const meta=document.createElement('span');meta.textContent=`${item.room_type==='coin'?`${item.stake} 币场`:'休闲场'} · ${phaseText(item.phase)} · ${item.occupied}/${item.capacity} 人${item.mine?' · 我已入座':''}`;
    button.append(title,meta);button.addEventListener('click',()=>enterRoom(item.room_id));list.append(button);
  }
}

async function enterRoom(roomId,existingToken=null){
  const token=existingToken??++generation;followStop?.();followStop=null;feedback('房间加载中…');
  try{
    const value=await client.snapshot(roomId);if(token!==generation)return;
    setRoom(value);renderRoom();feedback();const uid=await client.identity();if(token!==generation)return;
    await client.kvPut(`drawguess:last-room:${uid}`,roomId);if(token!==generation)return;
    followStop=client.follow(roomId,room.cursor,update=>{
      if(token!==generation)return;
      if(update.snapshot){setRoom(update.snapshot);renderRoom();return;}
      room.cursor=update.cursor;board.applyEvents(update.events||[],room.state.turn_id);
    },error=>{if(token===generation)feedback(`${error.message}，正在重连…`);});
    markReady();
  }catch(error){if(token===generation)feedback(error.message||'房间加载失败');}
}

function renderPlayers(){
  const holder=$('#players');holder.replaceChildren();const state=room.state;const total=state.phase==='waiting'?8:state.players.length;
  for(let index=0;index<total;index++){
    const player=state.players[index],seat=document.createElement('div');seat.className='seat';
    if(!player)seat.classList.add('empty-seat');if(index===state.drawer_seat)seat.classList.add('drawer');if(player?.guessed)seat.classList.add('guessed');
    const avatar=document.createElement('div');avatar.className='avatar';avatar.textContent=player?player.name.slice(0,1):'+';
    const name=document.createElement('div');name.className='seat-name';name.textContent=player?.name||'空位';
    const meta=document.createElement('div');meta.className='seat-meta';
    meta.textContent=player?(state.phase==='waiting'?(player.ready?'已准备':player.is_host?'房主':'未准备'):`${player.score} 分`):'等待加入';
    seat.append(avatar,name,meta);holder.append(seat);
  }
}

function renderMessages(){
  const list=$('#messages');list.replaceChildren();
  for(const item of room.messages||[]){const line=document.createElement('div');line.className='message';const name=document.createElement('strong');name.textContent=item.name;const text=document.createElement('span');text.textContent=item.text;line.append(name,text);list.append(line);}list.scrollTop=list.scrollHeight;
}

function inputPermission(){
  const state=room.state,self=room.self_seat;
  if(state.phase==='closed')return ['房间已关闭',false];
  if(self===null)return ['观战中 · 可以聊天',true];
  if(state.phase==='drawing'){
    if(self===state.drawer_seat)return ['作画中 · 可以聊天',true];
    if(state.players[self]?.guessed)return ['已猜中 · 可以聊天',true];
    return ['',true];
  }
  if(state.phase==='selecting'&&self===state.drawer_seat)return ['选词中 · 可以聊天',true];
  return ['',true];
}

function renderChatContext(){
  const state=room.state,self=room.self_seat,isDrawer=self===state.drawer_seat;
  const prompt={waiting:'房间聊天',selecting:'等待画手选词',revealing:'答案揭晓',finished:'赛后聊天',closed:'房间已关闭'}[state.phase]
    ||(isDrawer?`请画：${state.answer}`:`${state.players[state.drawer_seat]?.name||'画手'}正在作画`);
  $('#prompt').textContent=prompt;
  $('#word-hint').textContent=['drawing','revealing'].includes(state.phase)&&state.word_length?`${state.word_length} 个字`:'';
  const [reason,enabled]=inputPermission();$('#input-reason').textContent=reason;$('#chat-input').disabled=!enabled;$('#chat-send').disabled=!enabled;
}

function renderRoom(){
  document.body.classList.add('room-open');show('#lobby',false);show('#room-view');const state=room.state;
  window.MoyuClubRuntime?.setRoomContext?.({game:'drawguess',roomId:room.room_id,host:room.creator_name||state.players.find(player=>player?.is_host)?.name||'玩家'});
  const titles={waiting:'候场房间',selecting:'选择题目',drawing:'正在作画',revealing:'答案揭晓',finished:'本局排行'};
  $('#phase-label').textContent=phaseText(state.phase);$('#room-title').textContent=titles[state.phase]||'游戏房间';$('#room-code').textContent=`${room.creator_name||'玩家'}的房间`;
  $('#round-label').textContent=state.phase==='waiting'?'准备入座':state.phase==='finished'?'最终排名':`第 ${state.turn_index+1}/${state.players.length*2} 题`;
  renderPlayers();
  for(const id of ['#waiting','#choosing','#play-area','#reveal','#ranking'])show(id,false);
  if(state.phase==='waiting')renderWaiting();
  if(state.phase==='selecting')renderChoosing();
  if(['drawing','revealing'].includes(state.phase))renderPlay();
  if(state.phase==='revealing')renderReveal();
  if(state.phase==='finished')renderRanking();
  renderChatContext();renderMessages();updateTimer();
}

function renderWaiting(){
  show('#waiting');const self=room.self_seat;$('#waiting-copy').textContent=self===null?'房间还有空位，先到先得。':`已入座 · ${room.state.players.filter(Boolean).length}/8 人`;
  show('#claim-controls',self===null);show('#seat-controls',self!==null);
  if(self!==null){const player=room.state.players[self];$('#ready').textContent=player.ready?'取消准备':'准备';$('#ready').dataset.action=player.ready?'unready':'ready';const start=$('#start');start.hidden=!player.is_host;const canStart=room.state.players.length>=3&&room.state.players.every(item=>item.ready);start.disabled=!canStart;start.title=canStart?'':'至少三人且所有人准备后才能开始';}
}

function renderChoosing(){
  show('#choosing');const cards=$('#word-cards');cards.replaceChildren();const mine=room.self_seat===room.state.drawer_seat;
  $('#choose-wait').textContent=mine?'15 秒内未选择将自动开始':'画手正在挑选词语…';
  for(const word of room.state.candidates||[]){const button=document.createElement('button');button.className='word-card';button.type='button';button.textContent=word.answer;button.addEventListener('click',()=>sendAction('choose',{word_id:word.id}));cards.append(button);}
}

function renderPlay(){
  show('#play-area');const state=room.state,isDrawer=room.self_seat===state.drawer_seat&&state.phase==='drawing';
  show('#drawing-tools',isDrawer);board.setEditable(isDrawer);board.restore({turn_id:state.turn_id,canvas:room.canvas||[]});$('#draw-canvas').dataset.turnId=String(state.turn_id);
}

function renderReveal(){
  show('#reveal');$('#reveal').replaceChildren();const label=document.createElement('span');label.className='eyebrow';label.textContent='本题答案';const answer=document.createElement('div');answer.className='answer';answer.textContent=room.state.answer||'—';const note=document.createElement('p');note.className='muted';note.textContent='5 秒后进入下一题';$('#reveal').append(label,answer,note);
}

function renderRanking(){
  show('#ranking');const section=$('#ranking');section.replaceChildren();const title=document.createElement('h3');title.textContent='本局结算';const subtitle=document.createElement('p');subtitle.className='muted';subtitle.textContent='最终排名与得分 · 留在房间准备即可继续';const list=document.createElement('div');list.className='ranking-list';
  for(const item of room.state.ranking||[]){const row=document.createElement('div');row.className='rank-row';const rank=document.createElement('span');rank.className='rank-number';rank.textContent=`第 ${item.rank} 名`;const name=document.createElement('strong');name.textContent=item.name;const score=document.createElement('span');const seat=room.state.players.findIndex(value=>value.id===item.id);const payout=room.settlement?.payouts?.[seat]||0;const net=room.room_type==='coin'?payout-room.stake:null;score.textContent=`${item.score} 分${net===null?'':` · ${net>=0?'+':''}${net} 币`}`;row.append(rank,name,score);list.append(row);}
  const readiness=document.createElement('div');readiness.className='settlement-ready';for(const player of room.state.players){const item=document.createElement('span');item.className=player.ready?'ready':'';item.textContent=`${player.name} ${player.ready?'已准备':'未准备'}`;readiness.append(item);}
  const actions=document.createElement('div');actions.className='action-row';if(room.self_seat!==null){const me=room.state.players[room.self_seat];const ready=document.createElement('button');ready.type='button';ready.className=me.ready?'secondary':'primary';ready.textContent=me.ready?'取消准备':'准备下一局';ready.addEventListener('click',()=>sendAction(me.ready?'unready':'ready'));actions.append(ready);const leave=document.createElement('button');leave.type='button';leave.className='secondary';leave.textContent='退出房间';leave.addEventListener('click',()=>$('#back').click());actions.append(leave);if(me.is_host){const start=document.createElement('button');start.type='button';start.className='primary';const readyCount=room.state.players.filter(player=>player.ready).length;start.disabled=readyCount!==room.state.players.length;start.textContent=start.disabled?`等待准备 ${readyCount}/${room.state.players.length}`:'开始下一局';start.addEventListener('click',()=>sendAction('start'));actions.append(start);}}section.append(title,subtitle,list,readiness,actions);
}

async function sendAction(action,payload={}){
  if(!room)return;feedback();try{setRoom(await client.action(room.room_id,{turn_id:room.state.turn_id,version:room.state.version,action,payload}));renderRoom();}catch(error){feedback(error.message);}
}
async function sendChat(){
  if(!room||$('#chat-input').disabled)return;const text=$('#chat-input').value.trim();if(!text)return;
  $('#chat-send').disabled=true;try{await client.chat(room.room_id,{turn_id:room.state.turn_id,text});$('#chat-input').value='';setRoom(await client.snapshot(room.room_id));renderRoom();}catch(error){feedback(error.message);}finally{if(room)renderRoom();}
}
function updateTimer(){const value=secondsLeft();$('#timer').textContent=value===null?'--':`${value}s`;}
function setChatOpen(open){$('#draw-chat').classList.toggle('open',open);$('#draw-chat-toggle').setAttribute('aria-expanded',String(open));}

$('#refresh').addEventListener('click',()=>boot(true));$('#room-refresh').addEventListener('click',()=>room&&enterRoom(room.room_id));
$('#draw-chat-toggle').addEventListener('click',()=>setChatOpen(!$('#draw-chat').classList.contains('open')));$('#draw-chat-close').addEventListener('click',()=>setChatOpen(false));
$('#back').addEventListener('click',async()=>{if(room&&!['waiting','finished','closed'].includes(room.state.phase)&&!confirm('本局尚未结束。返回后轮次倒计时仍会继续，重新进入 Club 会回到本局。确定返回吗？'))return;generation++;followStop?.();followStop=null;try{if(room?.state.phase==='waiting'&&room.self_seat!==null)await client.action(room.room_id,{turn_id:room.state.turn_id,version:room.state.version,action:'leave',payload:{}});}catch(error){feedback(error.message);}const uid=await client.identity();await client.kvPut(`drawguess:last-room:${uid}`,null);room=null;rooms=await client.rooms();renderLobby();feedback();});
$('#claim').addEventListener('click',()=>sendAction('claim'));
document.querySelectorAll('[data-create-room]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const next=await client.create(button.dataset.createRoom,Number(button.dataset.stake));await enterRoom(next.room_id);}catch(error){feedback(error.message);}finally{button.disabled=false;}}));
$('#ready').addEventListener('click',()=>sendAction($('#ready').dataset.action||'ready'));$('#start').addEventListener('click',()=>sendAction('start'));
$('#chat-send').addEventListener('click',sendChat);$('#chat-input').addEventListener('compositionstart',()=>{composing=true;});$('#chat-input').addEventListener('compositionend',()=>{composing=false;});$('#chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!composing&&!event.isComposing){event.preventDefault();sendChat();}});
for(const button of document.querySelectorAll('[data-color]'))button.addEventListener('click',()=>{currentTool={...currentTool,tool:'pen',color:button.dataset.color};board.setTool(currentTool);document.querySelectorAll('[data-color]').forEach(item=>item.classList.toggle('active',item===button));$('#eraser').classList.remove('active');});
$('#eraser').addEventListener('click',()=>{currentTool={...currentTool,tool:'eraser',color:'#ffffff'};board.setTool(currentTool);$('#eraser').classList.add('active');});
$('#undo').addEventListener('click',()=>board.undo());$('#clear').addEventListener('click',()=>{if(confirm('确定清空本题画布吗？'))board.clear();});
timer=setInterval(updateTimer,500);window.addEventListener('pagehide',()=>unmount());

export function unmount(){generation++;followStop?.();followStop=null;clearInterval(timer);timer=null;board.destroy();client.dispose();window.MoyuClubRuntime?.clearRoomContext?.();}
boot();
