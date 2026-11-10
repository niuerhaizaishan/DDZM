const ranks=['3','4','5','6','7','8','9','10','J','Q','K','A','2'];
export function cardLabel(id){return id>=52 ? (id===52?'小王':'大王') : '♠♥♣♦'[id%4]+ranks[Math.floor(id/4)];}
export function toggleSelection(selected,id){const next=new Set(selected);if(next.has(id))next.delete(id);else next.add(id);return next;}
export function cardElement(id,small=false){
  const el=document.createElement(small?'span':'button');
  el.className=`card${small?' small':''}${id===53||id<52&&id%2===1?' red':''}`;
  if(!small){el.type='button';el.dataset.card=String(id);el.setAttribute('aria-pressed','false');}
  el.setAttribute('aria-label',cardLabel(id));
  const label=cardLabel(id),rank=id<52?label.slice(1):label,suit=id<52?label[0]:'★';
  for(const [name,text] of [['pip',rank],['suit',suit]]){const node=document.createElement('span');node.className=name;node.textContent=text;el.append(node);}
  return el;
}
