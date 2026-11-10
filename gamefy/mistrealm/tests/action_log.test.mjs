import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../publish/v3/game.js',import.meta.url),'utf8');
function fixture(){
 const nodes=Object.fromEntries(['action-reveal','action-reveal-content','modal'].map(id=>[id,{hidden:true,innerHTML:'',open:false,dataset:{}}]));
 const timers=new Map(),renders=[];let seq=0;
 const ctx=vm.createContext({$:id=>nodes[id],room:null,latestRoom:null,main:{inert:false},data:{transforms:{},cards:{c1:{name:'测试单位',art:'art.jpg',text:'部署效果'},l1:{name:'测试领袖',art:'leader.jpg',text:'领袖效果'}}},esc:s=>s,desc:c=>c.text,
  expedition:{catalogue:()=>({cards:{xb01:{name:'碎骨执旗兵',art:'bone.svg',text:'阵亡强化',power:3}}})},gameSettings:{animations:true},gameAudio:{play(){}},effectFeedback:{clear(){},snapshot(){return new Map();},play(){return false;},active:false},
  document:{querySelectorAll:()=>[],querySelector:()=>null},render:()=>renders.push(ctx.room.state.version),
  setTimeout:fn=>{timers.set(++seq,fn);return seq;},clearTimeout:id=>timers.delete(id)});
 vm.runInContext(source.match(/^const cardData=.+/m)[0],ctx);
 vm.runInContext('let revealQueue=[],revealTimer=null,revealCurrent=null;'+source.slice(source.indexOf('function clearReveal()'),source.indexOf('function showMatchLog()')),ctx);
 function state(log,id='room'){
  const players=[{name:'我',hand:[]},{name:'对手'}];
  return {room_id:id,state:{version:log.length,phase:'playing',seat:0,players,action_log:log,
   action_frames:log.map(e=>({version:e.id,log_id:e.id,event_id:['play','leader'].includes(e.kind)?e.id:null,played:null,landing:null,state:{players,phase:'playing'}}))}};
 }
 return {ctx,nodes,timers,renders,state,sync:(prev,next)=>{ctx.latestRoom=next;ctx.syncActionLog(prev,next);}};
}
const entry=(id,kind='play',seat=0)=>({id,kind,seat,card:kind==='leader'?'l1':'c1'});
test('initial snapshot and repeated sync do not replay old actions',()=>{
 const f=fixture(),a=f.state([entry(1)]);f.sync(null,a);assert.equal(f.timers.size,0);
 f.sync(a,a);assert.equal(f.nodes['action-reveal'].hidden,true);
 const b=f.state([...a.state.action_log,entry(2)]);f.sync(a,b);assert.equal(f.timers.size,1);
 f.sync(b,b);f.ctx.nextReveal();assert.equal(f.nodes['action-reveal'].hidden,true);
});
test('board waits for each reveal and applies intermediate AI states in order',()=>{
 const f=fixture(),a=f.state([]),b=f.state([entry(1),entry(2,'leader',1)]);f.sync(null,a);f.sync(a,b);
 assert.equal(f.ctx.room.state.version,0);assert.equal(f.ctx.main.inert,true);
 assert.match(f.nodes['action-reveal-content'].innerHTML,/己方 · 使用卡牌/);
 f.ctx.nextReveal();assert.equal(f.ctx.room.state.version,1);
 assert.equal(f.ctx.room.state.action_log.length,1);
 assert.match(f.nodes['action-reveal-content'].innerHTML,/对手 · 领袖技能/);
 f.ctx.nextReveal();assert.equal(f.ctx.room,b);assert.equal(f.ctx.main.inert,false);
 assert.equal(f.nodes['action-reveal'].hidden,true);assert.equal(f.timers.size,0);
});
test('new snapshots append while animating; choice becomes available only after playback',()=>{
 const f=fixture(),a=f.state([]),b=f.state([entry(1)]),c=f.state([entry(1),entry(2,'leader',1)]);
 c.state.pending={actor:0,options:[{token:'target'}]};f.sync(null,a);f.sync(a,b);f.sync(b,c);
 assert.equal(f.ctx.room,a);f.ctx.nextReveal();assert.equal(f.ctx.room.state.pending,null);
 f.ctx.nextReveal();assert.equal(f.ctx.room.state.pending.options[0].token,'target');assert.equal(f.ctx.main.inert,false);
});
test('changing rooms cancels timers without revealing stale board',()=>{
 const f=fixture(),a=f.state([]);f.sync(null,a);f.sync(a,f.state([entry(1),entry(2,'choose')]));
 const other=f.state([],'another-room');f.sync(f.ctx.latestRoom,other);
 assert.equal(f.timers.size,0);assert.equal(f.nodes['action-reveal'].hidden,true);assert.equal(f.ctx.room,other);assert.equal(f.ctx.main.inert,false);
});
test('choice-only updates apply immediately and do not replay the card',()=>{
 const f=fixture(),a=f.state([entry(1)]),b=f.state([entry(1),entry(2,'choose')]);f.sync(null,a);f.sync(a,b);
 assert.equal(f.ctx.room,b);assert.equal(f.timers.size,0);assert.equal(f.nodes['action-reveal'].hidden,true);
});
test('fade completes before final battle state is displayed',()=>{
 const f=fixture(),a=f.state([]),b=f.state([entry(1,'leader')]);f.sync(null,a);f.sync(a,b);
 const reveal=[...f.timers.values()][0];reveal();assert.equal(f.ctx.room,a);
 const landing=[...f.timers.values()].at(-1);landing();assert.equal(f.ctx.room,b);
});
test('landing coordinates follow the rotated phone surface',()=>{
 const f=fixture();f.nodes['game-shell']={offsetWidth:844,getBoundingClientRect:()=>({width:390,height:844})};
 f.ctx.document.documentElement={classList:{contains:()=>true}};
 const art={getBoundingClientRect:()=>({x:100,y:100,width:60,height:90})};
 const target={getBoundingClientRect:()=>({x:200,y:300,width:60,height:90})};
 assert.equal(f.ctx.revealTravel(art,target),'translate(200px,-100px) scale(1)');
});

test('effect beats finish before a following action or target choice is exposed',()=>{
 const f=fixture(),a=f.state([]),b=f.state([entry(1,'choose')]),c=f.state([entry(1,'choose'),entry(2,'choose')]);
 let complete;f.ctx.effectFeedback.play=(steps,old,done)=>{if(!steps?.length)return false;f.ctx.effectFeedback.active=true;complete=()=>{f.ctx.effectFeedback.active=false;done();};return true;};
 b.state.action_frames[1-1].effects=[{events:[{kind:'power',amount:1}]}];
 c.state.pending={actor:0,options:[{token:'next'}]};
 f.sync(null,a);f.sync(a,b);assert.equal(f.ctx.main.inert,true);
 f.sync(b,c);assert.equal(f.ctx.room.state.version,1);assert.equal(f.ctx.room.state.pending,null);
 complete();assert.equal(f.ctx.room,c);assert.equal(f.ctx.main.inert,false);
});


test('disabling animations releases queued actions and applies pending choices immediately',()=>{
 const f=fixture(),a=f.state([]),b=f.state([entry(1)]),c=f.state([entry(1),entry(2)]);
 f.sync(null,a);f.sync(a,b);assert.equal(f.ctx.main.inert,true);
 f.ctx.gameSettings.animations=false;c.state.pending={actor:0,options:[{token:'target'}]};
 f.sync(b,c);assert.equal(f.ctx.room,c);assert.equal(f.ctx.main.inert,false);
 assert.equal(f.timers.size,0);assert.equal(f.nodes['action-reveal'].hidden,true);
});

test('expedition cards use the same reveal sequence and upgraded inspection data',()=>{
 const f=fixture(),a=f.state([]),b=f.state([{...entry(1),card:'xb01'}]);
 f.sync(null,a);f.sync(a,b);assert.match(f.nodes['action-reveal-content'].innerHTML,/碎骨执旗兵/);
 assert.equal(vm.runInContext("cardData({card:'xb01',expedition_upgrade:2}).power",f.ctx),5);
 f.ctx.nextReveal();assert.equal(f.ctx.room,b);assert.equal(f.ctx.main.inert,false);
});
