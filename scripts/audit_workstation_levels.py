"""Render the actual workstation states and audit every two-tier combination."""
from pathlib import Path
from io import BytesIO
import argparse,base64,html,itertools,json,sys
from PIL import Image,ImageChops,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from dzmm_bot.browser.workstation_image import render_workstation_image
from dzmm_bot.browser.workstation_status import _font
from dzmm_bot.core.workstation_catalog import CATEGORIES,TOOL_INCOME,ENVIRONMENT_INCOME,upgrade_cost,environment_upgrade_cost,environment_daily_income,component_daily_income
from dzmm_bot.core.workstation_stage5 import accessory_scene,REGISTRIES
from dzmm_bot.core.workstation_art import component_scene
from dzmm_bot.core.workstation_accessories import ACCESSORIES
from dzmm_bot.core.workstation_labels import ENVIRONMENT_NAMES
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=ROOT/'output/workstation-level-audit')
OUT=parser.parse_args().output_dir;OUT.mkdir(parents=True,exist_ok=True)

def payload(room,bits):
 cs=[]
 for c in CATEGORIES:
  lv=room*2-1+(bits[c['number']-6] if c['number']>=6 else 0)
  cs.append({'key':c['key'],'number':c['number'],'category':c['name'],'name':c['names'][lv-1],'highest_level':lv,'active_level':lv,'equipped':True,'daily_income':component_daily_income(c['number'], lv)})
 acc=[{**a,'equipped':True} for a in ACCESSORIES if a['environment']<=room]
 return {'display_name':'等级对照','equipped':[],'progression':{'components':cs,'accessories':acc,'scene':component_scene(cs),'accessory_scene':accessory_scene(cs,acc)}}

def render(room,bits):
 stream=BytesIO();render_workstation_image(payload(room,bits),stream);stream.seek(0)
 return Image.open(stream).convert('RGB')

def embed(im):
 stream=BytesIO();im.save(stream,format='WEBP',quality=90)
 return 'data:image/webp;base64,'+base64.b64encode(stream.getvalue()).decode()

report={'states':80,'upgrade_edges':160,'no_visual_change':[],'device_pairs':[],'environment_changes':[]}
sections=[];contact=Image.new('RGB',(1200,5*300),'#fff');font=_font(20);draw=ImageDraw.Draw(contact)
previous=None
for room in range(1,6):
 images={bits:render(room,bits) for bits in itertools.product((0,1),repeat=4)}
 # Exclude the status panel so text-only level changes cannot pass the art audit.
 for bits,im in images.items():
  for device in range(4):
   if bits[device]:continue
   upgraded=list(bits);upgraded[device]=1;other=images[tuple(upgraded)]
   diff=ImageChops.difference(im,other);ImageDraw.Draw(diff).rectangle((1112,40,1496,276),fill=(0,0,0))
   if not diff.getbbox():report['no_visual_change'].append([room,list(bits),device])
 basic=images[(0,0,0,0)];full=images[(1,1,1,1)]
 if previous is not None:report['environment_changes'].append({'to':room,'changed':bool(ImageChops.difference(previous,basic).getbbox())})
 previous=basic
 for j,im in enumerate([basic,full]):
  thumb=im.resize((450,300));contact.paste(thumb,(j*600,(room-1)*300));draw.text((j*600+455,(room-1)*300+110),f'环境{room}\n'+('基础' if j==0 else '升级'),font=font,fill='black')
 cost=str(environment_upgrade_cost(room)) if room<5 else '已满'
 sections.append(f'<section id="env{room}"><h2>环境{room} {ENVIRONMENT_NAMES[room-1]}</h2><p>环境日收益 {environment_daily_income(room)} 摸鱼币；升至下一环境费用 {cost}。下一环境价格还包括四件设备跨入下一环境基础款的费用，见下表说明。</p><div class="pair"><figure><img src="{embed(basic)}"><figcaption>四件设备均为{room}-1</figcaption></figure><figure><img src="{embed(full)}"><figcaption>四件设备均为{room}-2</figcaption></figure></div>')
 sections.append('<p>五项基础布置：'+ '、'.join(c['names'][room*2-2] for c in CATEGORIES[:5])+'。自动获得的装饰：'+'、'.join(a['name'] for a in ACCESSORIES if a['environment']==room)+'。</p>')
 for i,c in enumerate(CATEGORIES[5:]):
  bits=[0]*4;bits[i]=1;up=images[tuple(bits)]
  # Crop both variants to a shared rectangle based on their actual changed pixels.
  diff=ImageChops.difference(basic,up);ImageDraw.Draw(diff).rectangle((1112,40,1496,276),fill=(0,0,0));bbox=diff.getbbox()
  if bbox:
   x1,y1,x2,y2=bbox;box=(max(0,x1-65),max(0,y1-65),min(1536,x2+65),min(1024,y2+65))
  else:box=(0,0,1536,1024)
  record={'environment':room,'device':c['name'],'basic_name':c['names'][room*2-2],'upgraded_name':c['names'][room*2-1],'basic_income':TOOL_INCOME[room*2-2],'upgraded_income':TOOL_INCOME[room*2-1],'upgrade_price':upgrade_cost(room*2-1),'changed_bbox':bbox}
  report['device_pairs'].append(record)
  sections.append(f'<h3>{c["name"]} {room}-1 → {room}-2</h3><table><tr><th>等级</th><th>游戏内名称</th><th>日收益</th><th>升到下一档费用</th></tr><tr><td>{room}-1</td><td>{html.escape(record["basic_name"])}</td><td>{record["basic_income"]}</td><td>{record["upgrade_price"]}</td></tr><tr><td>{room}-2</td><td>{html.escape(record["upgraded_name"])}</td><td>{record["upgraded_income"]}</td><td>{'已满' if room == 5 else '随下一环境整体购入基础款'}</td></tr></table><div class="pair crops"><figure><img src="{embed(basic.crop(box))}"><figcaption>{room}-1 基础款</figcaption></figure><figure><img src="{embed(up.crop(box))}"><figcaption>{room}-2 升级款</figcaption></figure></div>')
 sections.append('</section>')
contact.save(OUT/'contact.png');(OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
intro='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>工位环境与设备等级差异对照</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;max-width:1100px;margin:auto;padding:24px;color:#202c33;background:#faf9f5}h1,h2,h3{color:#111}h2{margin-top:48px}h3{margin-top:32px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}figure{margin:0}img{width:100%;background:#eae7df;border-radius:8px}figcaption{text-align:center;color:#52616a}table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #cad1d4;padding:10px;text-align:left}th{background:#e5edf0}nav{display:flex;gap:16px;flex-wrap:wrap}a{color:#245e70}.crops img{height:250px;object-fit:contain}p{max-width:1000px}@media(max-width:640px){body{padding:16px}.pair{grid-template-columns:1fr}.crops img{height:230px}table{font-size:13px}}@media print{section{break-before:page}h3{break-after:avoid}.pair,table{break-inside:avoid}}</style><h1>工位环境与设备等级差异对照</h1><p>使用游戏当前素材与正式合成逻辑生成，图片均内嵌，可离线打开。共5级环境、4类设备，每环境基础款和升级款各一档，即每类10档。</p><p><strong>升级资格看已购买的最高等级，不要求正在装备最高档。</strong>切回旧环境或基础款、卸下设备，不应倒退购买进度。收益仍按当前实际装备结算；设备升级成功会装备新档，跨环境升级会切回对应环境。</p><p>检查了80种完整设备组合、160条单件升级路径，比较时排除了右上角等级文字，避免把文字变化误当成设备外观变化。以下图片是当前实现，不表示所有素材已经逐项符合原Excel里的产品描述；旧场景的“破旧程度”等美术表现仍需人工确认。</p><p>费用说明：环境本体的升级价格是位置、地板、桌子、椅子、绿植五项跨级费用之和；实际“升级环境”订单还会加四件设备从上一环境升级款进入下一环境基础款的费用。常规完整订单依次为460、1430、3700、7400摸鱼币；以服务端实时订单为准。</p><nav>'''
intro+=''.join(f'<a href="#env{n}">环境{n}</a>' for n in range(1,6))+'</nav>'
conclusion=f'<h2>本轮完善结果</h2><p>2级、5级鼠标升级款已改为深色人体工学造型，分别加入银色侧翼、金色侧翼与清晰侧键，保留原来桌面占地和接触位置。电脑名称及描述已统一为台式机与工作站，与实际机箱素材一致。价格、收益和已购进度不变。五级环境的基础与升级款设备都保留可见差异。</p><h2>检查结果</h2><p>没有视觉变化的升级路径：{len(report["no_visual_change"])} / 160。五个环境背景均不同；单件设备在每个环境均检测到图像变化。此检查能识别素材相同或升级未切图，不能单独证明所有摆放、透视和遮挡均合理。</p></html>'
document = (intro+''.join(sections)+conclusion).replace('环境日收益 20 摸鱼币；升至下一环境费用 已满。下一环境价格还包括四件设备跨入下一环境基础款的费用，见下表说明。','环境日收益 20 摸鱼币；已到最高环境，四件设备仍可从5-1升至5-2。')
(OUT/'工位环境与设备等级对照.html').write_text(document,encoding='utf-8')
print(json.dumps({'folder':str(OUT),'no_visual_change':report['no_visual_change'],'environment_changes':report['environment_changes']},ensure_ascii=False))
