"""Name and captured equipment levels, baked into accessory scene exports."""
from pathlib import Path
from dzmm_bot.core.workstation_labels import ENVIRONMENT_NAMES
from PIL import Image, ImageDraw, ImageFont


def _font(size):
    for path in ('C:/Windows/Fonts/msyh.ttc',
                 '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                 '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RuntimeError('Workstation image exports require a Chinese font (Microsoft YaHei, Noto CJK or WenQuanYi)')


def _level_label(level):
    level = int(level)
    return f'{(level + 1) // 2}-{1 if level % 2 else 2}'


def draw_stage5_status(canvas, payload, environment=5):
    overlay = Image.new('RGBA', canvas.size)
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((1114,42,1494,274),radius=14,fill=(18,25,34,207),outline=(234,224,205,50))
    title = str(payload['display_name'])[:64] + '的工位'
    font = _font(32)
    if draw.textlength(title,font=font) > 328:
        while title and draw.textlength(title+'…',font=font)>328: title=title[:-1]
        title+='…'
    draw.text((1140,65),title,font=font,fill='#fdf7eb',anchor='lt')
    environment_components = [item for item in payload['progression']['components']
                              if item.get('number', 1 if item.get('key') not in {'computer', 'monitor', 'keyboard', 'mouse'} else 6) <= 5]
    environment_level = min((item['active_level'] for item in environment_components), default=environment * 2)
    draw.text((1140,114),f'工位 {_level_label(environment_level)}',font=_font(22),fill='#e9ca93',anchor='lt')
    environment_name = payload['progression'].get('environment_name') or ENVIRONMENT_NAMES[environment - 1]
    environment_font = _font(20)
    if draw.textlength(environment_name, font=environment_font) > 154:
        while environment_name and draw.textlength(environment_name+'…', font=environment_font) > 154:
            environment_name = environment_name[:-1]
        environment_name += '…'
    draw.text((1314,116),environment_name,font=environment_font,fill='#c0c8d0',anchor='lt')
    draw.line((1140,152,1468,152),fill=(231,232,228,46))
    states={item['key']:item for item in payload['progression']['components']}
    display_numbers = {'computer': 2, 'monitor': 3, 'keyboard': 4, 'mouse': 5}
    for i,(key,name) in enumerate(zip(('computer','monitor','keyboard','mouse'),('电脑','显示器','键盘','鼠标'))):
        x,y=1140+i%2*171,174+i//2*42
        state=states[key]
        draw.text((x,y),name,font=_font(21),fill='#c0c8d0',anchor='lt')
        label=_level_label(state['active_level']) if state['equipped'] else '未装备'
        draw.text((x+106,y),label,font=_font(19 if not state['equipped'] else 21),fill='#fdf7eb',anchor='lt')
    canvas.alpha_composite(overlay)
