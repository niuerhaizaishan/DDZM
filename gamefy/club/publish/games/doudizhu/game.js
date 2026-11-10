import {DoudizhuClient,withTimeout} from './client.js';
import {cardElement,toggleSelection} from './cards.js';
import {platformLoading} from '../runtime.js';
import {moduleEnvironment} from '../module-document.js';

const environment=moduleEnvironment();
const document=environment.document;
const location=environment.location;

const $=id=>document.getElementById(id);
const kinds={single:'单张',pair:'对子',triple:'三张',triple_single:'三带一',triple_pair:'三带一对',straight:'顺子',pair_straight:'连对',airplane:'飞机',airplane_single:'飞机带单',airplane_pair:'飞机带对',four_single:'四带二',four_pair:'四带两对',bomb:'炸弹',rocket:'王炸'};
const phases={waiting:'等待三人入座准备',bidding:'叫分定地主',playing:'正在对局',finished:'本局结束',cancelled:'房间已取消'};
const sdk=window.MoyuClubRuntime?.sdk??window.dzmm;
let client,state,roomId=null,stop=null,selected=new Set(),busy=false,handKey='',controlsKey='',hintIndex=0,lastVersion=null,clockOffset=0;
let navigation=0,savedRoomWrites=Promise.resolve();
let booting=false,bootStage='start',bootStarted=0,tickTimer=null;
const loading=platformLoading(sdk);
function startupStage(stage,message){
  if(!booting)return;
  bootStage=stage;feedback(message);
  loading?.progress?.({phase:'runtime_initializing',message});
  sdk?.log?.info?.('斗地主启动阶段',{stage,elapsedMs:Date.now()-bootStarted},'DDZ_BOOT_STAGE');
}
const text=(id,value)=>{$(id).textContent=value;};
function feedback(value,animate=false){const el=$('feedback');el.classList.remove('celebrate');text('feedback',value);if(animate){void el.offsetWidth;el.classList.add('celebrate');}}
function button(label,action,payload={}){const b=document.createElement('button');b.textContent=label;b.dataset.action=action;if(action==='bid')b.dataset.score=payload.score;b.onclick=()=>perform(action,payload);return b;}
function player(i){
  const p=state.players[i],el=document.createElement('div');el.className='player'+(state.turn===i?' active':'');
  const name=document.createElement('strong');name.textContent=p?p.name:'等待入座';el.append(name);
  const info=document.createElement('small');
  info.textContent=!p?'空席位':state.phase==='waiting'?(p.ready?'已准备':'未准备'):`${state.landlord===null?'待定':state.landlord===i?'地主':'农民'} · 剩 ${p.count} 张${p.count<=2?'！':''}${p.trustee?' · 托管':''}${p.online?' · 在线':' · 离线'}`;
  el.append(info);return el;
}
function paintHand(){
  const key=JSON.stringify([state.hand,[...selected]]);if(key===handKey)return;handKey=key;
  $('hand').replaceChildren(...[...state.hand].sort((a,b)=>b-a).map(id=>{const el=cardElement(id);el.classList.toggle('selected',selected.has(id));el.setAttribute('aria-pressed',String(selected.has(id)));return el;}));
}
function tick(){
  if(!state?.deadline){text('countdown','');return;}
  const seconds=Math.max(0,Math.ceil((Date.parse(state.deadline)-(Date.now()+clockOffset))/1000));
  text('countdown',state.phase==='waiting'?`准备剩余 ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`:`${state.players[state.turn]?.name||''} · ${seconds} 秒`);
}
function render(next,error){
  if(error){feedback(error.message);return;}
  if(!next||next.id!==roomId)return;
  if(state?.round_id!==next.round_id){selected.clear();hintIndex=0;}
  if(state&&next.round_id===state.round_id&&next.version<state.version)return;
  state=next;clockOffset=Date.parse(next.server_time)-Date.now();
  window.MoyuClubRuntime?.setRoomContext?.({game:'doudizhu',roomId,host:state.creator_name||state.players[0]?.name||'玩家'});
  selected=new Set([...selected].filter(c=>state.hand.includes(c)));
  document.body.classList.add('table-open');$('lobby').hidden=true;$('table').hidden=false;
  text('room-label',`${state.creator_name||'玩家'}的房间`);text('multiplier',`× ${state.multiplier}`);
  const self=state.seat,others=self===null?[0,1,2]:[(self+1)%3,(self+2)%3];
  $('opponents').replaceChildren(...others.map(player));$('self').replaceChildren(...(self===null?[]:[player(self)]));
  $('bottom').replaceChildren(...(state.bottom.length?state.bottom.map(id=>cardElement(id,true)):Array.from({length:3},()=>{const el=document.createElement('span');el.className='card small back';el.setAttribute('aria-label','未公开底牌');return el;})));
  text('phase-label',phases[state.phase]);tick();
  $('plays').replaceChildren(...state.table.map((p,i)=>{const el=document.createElement('div');el.className='play';const name=document.createElement('small');name.textContent=state.players[i]?.name||'';el.append(name);if(!p)return el;if(p.kind==='pass'){const value=document.createElement('span');value.className='play-pass';value.textContent='不出';el.append(value);return el;}const cards=document.createElement('div');cards.className='played-cards';cards.style.setProperty('--played-count',String(p.cards.length));cards.setAttribute('aria-label',kinds[p.kind]);cards.replaceChildren(...p.cards.map(id=>cardElement(id,true)));el.append(cards);return el;}));
  const key=JSON.stringify([state.phase,state.seat,state.version]);
  if(key!==controlsKey){
    controlsKey=key;hintIndex=0;$('actions').replaceChildren();
    $('claim-panel').hidden=state.phase!=='waiting'||self!==null||!state.players.includes(null);
    if(self!==null&&state.phase==='waiting')$('actions').append(button(state.players[self].ready?'取消准备':'准备',state.players[self].ready?'unready':'ready'),button(state.rematch_waiting?'退出并结束房间':'离开席位','leave'));
    if(self!==null&&state.phase==='bidding'&&state.turn===self){for(const score of [0,1,2,3])if(!score||score>state.bid)$('actions').append(button(score?`${score} 分`:'不叫','bid',{score}));}
    if(self!==null&&['bidding','playing'].includes(state.phase))$('actions').append(button(state.players[self].trustee?'取消托管':'托管',state.players[self].trustee?'resume':'takeover'));
    if(self!==null&&state.phase==='finished'){
      const ready=state.players[self].ready;
      $('actions').append(button(ready?'取消准备':'准备下一局',ready?'unready':'ready'));
      const leave=document.createElement('button');leave.textContent='退出房间';leave.className='quiet';leave.onclick=()=>lobby();$('actions').append(leave);
      if(state.is_host){const start=button('开始下一局','start');const readyCount=state.players.filter(player=>player?.ready).length;start.disabled=readyCount!==3;start.textContent=start.disabled?`等待准备 ${readyCount}/3`:'开始下一局';$('actions').append(start);}
    }
  }
  const myTurn=self!==null&&state.phase==='playing'&&state.turn===self;
  $('play-actions').hidden=!myTurn;$('pass').disabled=!state.previous;$('pass').title=state.previous?'':'首家必须出牌';
  paintHand();
  $('messages').replaceChildren(...state.messages.map(m=>{const el=document.createElement('p');el.textContent=`${m.name}：${m.text}`;return el;}));
  const canChat=['waiting','bidding','playing','finished'].includes(state.phase);$('chat-input').disabled=!canChat;$('chat-send').disabled=!canChat;
  $('result').hidden=!state.result;
  if(state.result){
    const title=document.createElement('h2');title.textContent=self===null?(state.result.winner==='landlord'?'地主胜利':'农民胜利'):(state.result.winners.includes(self)?'本局胜利':'本局落败');
    const detail=document.createElement('p');detail.className='settle-summary';detail.textContent=`${state.result.winners.map(i=>state.players[i]?.name).join('、')} 获胜 · ${state.multiplier} 倍${state.result.spring==='spring'?' · 春天':state.result.spring==='reverse_spring'?' · 反春':''}`;
    const rows=document.createElement('div');rows.className='settle-rows';(state.players||[]).forEach((player,index)=>{if(!player)return;const row=document.createElement('article');row.className=state.result.winners.includes(index)?'winner':'';const info=document.createElement('div');const name=document.createElement('strong');name.textContent=`${player.name} · ${state.landlord===index?'地主':'农民'}`;const note=document.createElement('small');const payout=state.settlement?.payouts?.[index]||0;const net=state.room_type==='coin'?payout-state.stake:0;note.textContent=state.room_type==='coin'?`摸鱼币 ${net>=0?'+':''}${net}`:`剩余 ${state.final_hands?.[index]?.length||0} 张`;info.append(name,note);const cards=document.createElement('div');cards.className='settle-cards';(state.final_hands?.[index]||[]).sort((a,b)=>b-a).forEach(id=>cards.append(cardElement(id)));row.append(info,cards);rows.append(row);});
    const ready=document.createElement('p');ready.className='settle-ready';ready.textContent=state.players.map(player=>`${player.name} ${player.ready?'已准备':'未准备'}`).join(' · ');
    $('result').replaceChildren(title,detail,rows,ready);
  }
  if(lastVersion!==null&&lastVersion!==state.version){const event=state.events.at(-1);if(event?.play)feedback(`${state.players[event.seat]?.name} · ${kinds[event.play.kind]}`,['straight','pair_straight','airplane','airplane_single','airplane_pair','bomb','rocket'].includes(event.play.kind));if(state.result?.spring)feedback(state.result.spring==='spring'?'春天！':'反春！',true);}
  lastVersion=state.version;
}
async function perform(action,payload={}){
  if(busy||!state)return;busy=true;
  const id=roomId,envelope={round_id:state.round_id,version:state.version,request_id:crypto.randomUUID(),action,payload};
  try{const next=await client.action(id,envelope);selected.clear();feedback('');render(next);}
  catch(error){feedback(error.message);try{render(await client.snapshot(id));}catch{}}
  finally{busy=false;}
}
function rememberRoom(id,uid=client.uid){
  const generation=navigation;
  savedRoomWrites=savedRoomWrites.then(async()=>{if(generation!==navigation||uid!==client.uid)return;await client.sdk.kv.put(`doudizhu:last-room:${uid}`,id,{flush:true});}).catch(()=>{});
}
async function enter(id){
  const generation=++navigation;
  const started=Date.now();let stage='request';
  const trace=(code)=>sdk?.log?.info?.(code,{elapsedMs:Date.now()-started},code);
  trace('DDZ_ROOM_ENTER');feedback('正在进入房间…');
  try{
  stop?.();roomId=id;state=null;selected.clear();controlsKey=handKey='';lastVersion=null;
  const next=await client.snapshot(id);if(generation!==navigation)return;
  trace('DDZ_ROOM_FETCHED');stage='render';render(next);feedback('');
  trace('DDZ_ROOM_RENDERED');stage='connection';
  stop=client.follow(id,render);
  trace('DDZ_ROOM_FOLLOW_STARTED');
  rememberRoom(id);
  }catch(e){
    if(generation!==navigation)return;
    const code=`DDZ_ROOM_${stage.toUpperCase()}_FAILED`;
    sdk?.log?.error?.(code,{stage,elapsedMs:Date.now()-started,status:e.status||null,errorType:e.name},code);
    feedback(`进入房间失败：${e.message}（${code}），请重试`);
    throw e;
  }
}
async function lobby(restore=false,preferredRoom=null){
  const generation=++navigation;
  stop?.();roomId=null;state=null;selected.clear();document.body.classList.remove('table-open');$('table').hidden=true;$('lobby').hidden=false;
  window.MoyuClubRuntime?.clearRoomContext?.();
  $('rooms').replaceChildren();
  startupStage('identity','正在读取玩家身份…');
  await client.identity(true);if(generation!==navigation)return;
  startupStage('rooms','正在连接游戏服务器…');
  const rooms=await client.rooms();if(generation!==navigation)return;
  if(typeof preferredRoom==='string'&&/^[a-f0-9-]{36}$/i.test(preferredRoom)&&rooms.some(room=>room.id===preferredRoom)){await enter(preferredRoom);return;}
  if(!restore)rememberRoom(null);
  if(restore){
    startupStage('storage','正在读取上次牌局…');
    const saved=(await withTimeout(client.sdk.kv.get(`doudizhu:last-room:${client.uid}`),'读取上次牌局'))?.value;
    if(generation!==navigation)return;
    if(typeof saved==='string'&&/^[a-f0-9-]{36}$/i.test(saved)&&rooms.some(room=>room.id===saved))try{startupStage('restore','正在恢复牌局…');await enter(saved);return;}catch(e){if(![403,404,409].includes(e.status))throw e;roomId=null;state=null;}
    else if(saved)rememberRoom(null);
  }
  $('rooms').replaceChildren(...rooms.map(r=>{const b=document.createElement('button');b.className='room-card';const copy=document.createElement('span');const title=document.createElement('strong');const meta=document.createElement('small');const action=document.createElement('b');title.textContent=`${r.creator_name}的牌桌`;meta.textContent=`${r.room_type==='coin'?`${r.stake} 币场`:'休闲场'} · ${phases[r.phase]} · ${r.occupied}/3 人`;action.textContent=r.phase==='waiting'?'加入牌桌':'进入观战';copy.append(title,meta);b.append(copy,action);b.onclick=()=>enter(r.id).catch(e=>feedback(e.message));return b;}));
  if(!rooms.length)text('rooms','暂无牌局，可以先开一桌');feedback('');
}
$('claim').onclick=()=>perform('claim');
document.querySelectorAll('[data-create-room]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const next=await client.create(button.dataset.createRoom,Number(button.dataset.stake));await enter(next.id);}catch(error){feedback(error.message);}finally{button.disabled=false;}});
function playSelected(){if(!selected.size){feedback('请先选择要出的牌');return;}perform('play',{cards:[...selected]});}
$('play').onclick=playSelected;
$('pass').onclick=()=>perform('pass');
$('hint').onclick=async()=>{try{const id=roomId,version=state.version,plays=await client.suggestions(id);if(id!==roomId||version!==state.version)return;if(!plays.length){feedback('没有能压过的牌，可以选择不出');return;}selected=new Set(plays[hintIndex++%plays.length].cards);paintHand();}catch(e){feedback(e.message);}};
$('hand').addEventListener('click',e=>{const card=e.target.closest('.card');if(card){selected=toggleSelection(selected,Number(card.dataset.card));paintHand();}});
let chatBusy=false;
async function sendChat(){if(chatBusy||!state)return;const value=$('chat-input').value.trim();if(!value)return;chatBusy=true;try{await client.chat(roomId,{round_id:state.round_id,request_id:crypto.randomUUID(),text:value});$('chat-input').value='';render(await client.snapshot(roomId));}catch(e){feedback(e.message);}finally{chatBusy=false;}}
$('chat-send').onclick=sendChat;$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();sendChat();}});
$('back').onclick=async()=>{if(['bidding','playing'].includes(state?.phase)&&!confirm('本局尚未结束。返回后将立即进入托管，重新进入 Club 会回到本桌。确定返回吗？'))return;try{if(state?.seat!==null&&['waiting','bidding','playing'].includes(state.phase))await client.action(roomId,{round_id:state.round_id,version:state.version,request_id:crypto.randomUUID(),action:'leave',payload:{}});}catch(e){feedback(e.message);}finally{lobby().catch(e=>feedback(e.message));}};
$('refresh').onclick=()=>boot();
async function boot(){
  if(booting)return;
  booting=true;bootStage='start';bootStarted=Date.now();$('refresh').disabled=true;
  loading?.progress?.({phase:'start',message:'正在启动斗地主'});
  try{
    if(!window.DOUDIZHU_CONFIG?.apiBase)throw new Error('游戏后端尚未配置');
    if(!sdk?.user)throw new Error('请从摸鱼 Club 进入');
    if(!client)client=new DoudizhuClient({sdk,apiBase:window.DOUDIZHU_CONFIG.apiBase});
    await lobby(true,new URLSearchParams(location.search).get('room'));
    sdk?.log?.info?.('斗地主启动完成',{elapsedMs:Date.now()-bootStarted},'DDZ_BOOT_READY');
    loading?.ready?.();
  }catch(e){
    const code=`DDZ_BOOT_${bootStage.toUpperCase()}`;
    const message=`${e.message}（${code}），可点击刷新重试`;
    feedback(message);
    sdk?.log?.error?.('斗地主启动失败',{stage:bootStage,elapsedMs:Date.now()-bootStarted,status:e.status||null},code);
    loading?.error?.(code,message);
  }finally{booting=false;$('refresh').disabled=false;}
}
tickTimer=setInterval(tick,500);boot();

export function unmount(){stop?.();stop=null;clearInterval(tickTimer);tickTimer=null;window.MoyuClubRuntime?.clearRoomContext?.();}
