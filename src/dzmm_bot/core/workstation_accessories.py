"""Environment-granted workstation accessories and their display metadata."""
from .workstation_catalog import CATEGORIES, UPGRADE_COSTS

CORE_KEYS = ('computer', 'monitor', 'keyboard', 'mouse')
_SETS = {
 1: [('desk-mat','素色织物桌垫','mouse'),('headphones','入门耳机与支架','computer')],
 2: [('desk-mat','暖灰大桌垫','mouse'),('headphones','奶油色无线耳机与支架','computer'),
     ('speakers','紧凑双音箱','monitor'),('desk-clock','小型桌面钟','keyboard')],
 3: [('desk-mat','暖棕皮质桌垫','mouse'),('headphones','舒适耳机与木质支架','computer'),
     ('speakers','桌面双音箱','monitor'),('microphone','USB桌面麦克风','computer'),
     ('pen-display','小型绘图板与笔','keyboard')],
 4: [('desk-mat','深色高级织物桌垫','mouse'),('headphones','监听耳机与支架','computer'),
     ('speakers','近场监听音箱','monitor'),('microphone','悬臂麦克风与桌夹','computer'),
     ('pen-display','专业绘图板与笔','keyboard'),('console','旋钮快捷控制器','keyboard')],
 5: [('desk-mat','皮质大桌垫','mouse'),('headphones','旗舰耳机与木质支架','computer'),
     ('speakers','双监听音箱','monitor'),('microphone','悬臂麦克风','computer'),
     ('console','快捷控制台','keyboard'),('pen-display','手写屏与数位笔','keyboard'),
     ('handheld','掌机与底座','computer'),('lightbar','屏幕挂灯','monitor')],
}
ACCESSORIES = tuple({'number': stage*100+i+1, 'environment':stage,'key':key,'name':name,'unlock_key':parent,
                     'unlock_level':stage*2,'price':UPGRADE_COSTS[stage*2-2]}
                    for stage,items in _SETS.items() for i,(key,name,parent) in enumerate(items))
BY_NUMBER = {item['number']:item for item in ACCESSORIES}


def accessory_display_note(item, active_environment):
    if item['environment'] == active_environment:
        return ''
    return f"仅在环境{item['environment']}显示；/切换工位 {item['environment']} 查看。"


def accessory_requirement(item):
    parent = next(c['name'] for c in CATEGORIES if c['key'] == item['unlock_key'])
    return f"环境五件均达到 Lv{item['environment'] * 2 - 1}，{parent}达到 Lv{item['unlock_level']}"


def unlocked(item, components):
    states={c['key']:c for c in components}
    return (all(c['highest_level']>=item['environment']*2-1 for key,c in states.items() if key not in CORE_KEYS)
            and states[item['unlock_key']]['highest_level']>=item['unlock_level'])
