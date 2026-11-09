from .workstation_labels import ENVIRONMENT_NAMES, DEVICE_NUMBERS, level_label, parse_device_level, RETIRED_COMMANDS
from .workstation_accessories import BY_NUMBER, accessory_requirement, accessory_display_note
from .workstation_actions import WorkstationActionError
from .workstation_catalog import (
    CATEGORIES,
    TOOL_INCOME,
    environment_daily_income,
    environment_name,
    environment_upgrade_cost,
    upgrade_cost,
)


def growth_overview(growth):
    current = f"环境{growth['active_environment']}" if growth['active_environment'] else '混合搭配'
    return (f"布置 {current}｜进度 {growth['highest_environment']}/5｜可切换至环境{growth['switchable_environment']}",
            f"设备 {growth['core_equipped_count']}/9｜配件 {growth['accessories_owned']}组（已装备 {growth['accessories_equipped']}组）")


def growth_prices(shop):
    # Keep the store footer short and stable. Detailed gate feedback is returned
    # by the corresponding upgrade command when the user attempts it.
    return ["可用指令：/升级工位或/升级装备 2至5"]


SHOP_DEVICE_ORDER = (6, 7, 8, 9)
SHOP_DISPLAY_NUMBER = {6: 2, 7: 3, 8: 4, 9: 5}
DEVICE_COMMAND_NUMBER = {2: 6, 3: 7, 4: 8, 5: 9}


def workstation_income_table(rules=None):
    lines = ["【工位收益表】", "环境类"]
    for level in range(1, 6):
        income = environment_daily_income(level, rules=rules)
        price = f"升级费用 {environment_upgrade_cost(level, rules=rules)}" if level < 5 else "已满级"
        lines.append(f"Lv{level} 收益{income}｜{price}")
    lines.append("设备类")
    for level, income in enumerate(rules['tool_income'] if rules else TOOL_INCOME, start=1):
        environment, tier = (level + 1) // 2, 1 if level % 2 else 2
        price = f"升级费用 {upgrade_cost(level, rules=rules)}" if level < len(TOOL_INCOME) else "已满级"
        lines.append(f"Lv{environment}-{tier} 收益{income}｜{price}")
    return "\n".join(lines)


def shop_device_line(item, currency):
    environment = item['environment']
    prefix = f"{SHOP_DISPLAY_NUMBER[item['number']]} {item['category']}：Lv.{environment}-"
    if item['status'] == 'environment_max':
        return prefix + f"2 · 已满"
    line = prefix + f"1→{environment}-2 · {item['price']}{currency}"
    if item['status'] == 'insufficient_balance':
        line += f" · 还差 {item['shortage']} {currency}"
    elif item['status'] == 'rank_locked':
        line += f" · 需要{item['required_rank']}"
    return line


def handle_equipment_command(repository, message, command, group_chat_id, *, workstation_links=None):
    if command in RETIRED_COMMANDS:
        return None
    if message.source_type != "group" or group_chat_id is None:
        return "请在已启用的群聊中使用工位指令。"
    parts = message.content.strip().split()
    if command == '/升级工位' and parts == ['/升级', '环境']:
        parts = ['/升级工位']
    if command == '/切换工位' and parts[1:2] == ['环境'] and len(parts) == 3:
        parts = ['/切换工位', parts[2]]
    if command in {'/升级装备', '/装备', '/卸下'} and len(parts) > 1:
        if parts[1] in DEVICE_NUMBERS:
            parts[1] = str(SHOP_DISPLAY_NUMBER[DEVICE_NUMBERS[parts[1]]])
        if command == '/装备' and len(parts) == 3:
            parsed_level = parse_device_level(parts[2])
            if parsed_level is None:
                return '用法：/装备 鼠标 2-1；也可填写总等级1至10。'
            parts[2] = str(parsed_level)
    if command == '/工位收益表':
        if len(parts) != 1:
            return '用法：/工位收益表；发送 /帮助 工位 查看玩法。'
        return workstation_income_table(repository.workstation_rules())
    if command in {'/升级工位', '/精修工位', '/切换工位'}:
        valid = (len(parts) == 2 and parts[1].isascii() and parts[1].isdigit() and
                 len(parts[1]) == 1 and 1 <= int(parts[1]) <= 5) if command == '/切换工位' else len(parts) == 1
        if not valid:
            return f"用法：{command}" + (' 环境编号（1至5）' if command == '/切换工位' else '') + '；/帮助 工位 查看玩法。'
        if repository.find_user(message.sender_platform_id) is None:
            return '请先使用 /入职 名字 加入摸鱼公司。'
        action = {'kind': {'/升级工位': 'advance', '/精修工位': 'polish', '/切换工位': 'view'}[command]}
        if command == '/切换工位':
            action['level'] = int(parts[1])
        try:
            result = repository.apply_workstation_action(message.sender_platform_id, action, None, None,
                message.received_at, inbound=(message.platform_message_id, group_chat_id))
            return (f"{result['title']}完成。\n实付 {result['price']} {result['currency_name']}；余额 {result['balance']} {result['currency_name']}。\n"
                    '新环境配件已自动获得。网页刷新可查看，装卸记录跨群共享。')
        except WorkstationActionError as error:
            return str(error)
    usage = {"/升级装备": "设备名称", "/购买装备": "配件编号（已停用）",
             "/装备": "设备名称 等级", "/卸下": "部件编号"}
    count = 3 if command == "/装备" else 2 if command in usage else 1
    accessory = (len(parts)>1 and parts[1].isascii() and parts[1].isdigit()
                 and len(parts[1])<=9 and int(parts[1]) in BY_NUMBER)
    if accessory and command=='/装备':count=2
    valid = len(parts) == count and all(p.isascii() and p.isdigit() and len(p) <= 9 and int(p) >= 1 for p in parts[1:])
    # Previously shared upgrade commands remain valid while clients refresh.
    if command == "/升级装备":
        valid = len(parts) in {2, 3} and all(p.isascii() and p.isdigit() and len(p) <= 9 and int(p) >= 1 for p in parts[1:])
    if command == "/装备商城":
        valid = len(parts) == 1 or len(parts) == 2 and parts[1] == "全部"
    if not valid:
        return f"用法：{command} {usage.get(command, '全部' if command == '/装备商城' else '')}；发送 /帮助 工位 查看。"
    employee = repository.find_user(message.sender_platform_id)
    if employee is None:
        return "请先使用 /入职 名字 加入摸鱼公司。"
    shop = repository.get_workstation_shop(message.sender_platform_id)
    currency = shop["currency_name"]
    settlement_note = "每日北京时间00:00自动结算，按结算时已装备的环境和设备发放。" if shop["income_settlement_enabled"] else "收益仅预览，自动结算尚未启用。"
    if accessory and command=='/购买装备':
        return '配件不再单独购买，升级到对应环境后自动获得；请使用 /升级工位。'
    if command in {"/升级装备", "/装备", "/卸下"}:
        number = int(parts[1])
        number = DEVICE_COMMAND_NUMBER.get(number, number)
        if command == "/升级装备":
            result = repository.upgrade_workstation_component(message.platform_message_id, message.sender_platform_id,
                number, int(parts[2]) if len(parts) == 3 else None, group_chat_id, message.received_at)
        elif accessory:
            result=repository.set_workstation_accessory(message.sender_platform_id,number,equipped=command=='/装备')
        else:
            result = repository.set_workstation_component(message.sender_platform_id, number,
                int(parts[2]) if command == "/装备" else None, equipped=command == "/装备")
        status = result["status"]
        if status == "upgraded":
            return (f"升级成功：{result['name']} {level_label(result['level'])}，已自动装备。\n"
                    f"实付 {result['cash_paid']} {currency}。\n"
                    f"当前余额：{result['balance']} {currency}；该部件预计 {result['daily_income']} {currency}/日。\n"
                    f"{settlement_note}刷新工位可查看新外观。")
        if status in {"equipped", "removed"}:
            note = accessory_display_note(BY_NUMBER[number], shop['growth']['active_environment']) if accessory and status == 'equipped' else ''
            selected = ' ' + level_label(int(parts[2])) if command == '/装备' and not accessory else ''
            return (f"已{'装备' if status == 'equipped' else '卸下'} {result['name']}{selected}。\n"
                    + (note + '\n' if note else '') +
                    f"预计工位日收入：{result['daily_income']} {currency}。{settlement_note}")
        return {
            'environment_bundle': '位置、地板、桌子、椅子、绿植随环境整体更换，请使用 /升级工位，不再单独升级或装卸。',
            'environment_max': '已拥有当前环境的升级档；请使用 /升级工位 迁入下一环境，再提升设备。',
            'environment_locked': '只能选择当前环境的基础档或升级档；切换环境请使用 /装备 环境 编号。',
            'legacy_mixed': '旧搭配尚未补齐，请使用 /升级工位 整套迁入下一环境。',
            "not_joined": "请先使用 /入职 名字 加入摸鱼公司。",
            "not_found": "部件编号不存在，请发送 /工位背包 查看。",
            "wrong_group": "请在已启用的群聊中升级装备。",
            "not_owned": f"该等级尚未解锁，当前最高 {level_label(result.get('level', 1))}。",
            "accessory_not_owned": "该配件将在升级到对应环境后自动获得。",
            "stale_level": f"等级已变化，当前已解锁 {level_label(result.get('level', 1))}；请重新查看 /工位背包，避免重复扣币。",
            "rank_locked": f"职级不足，需要{result.get('required_rank')}才能升级到 {level_label(result.get('next_level', 1))}；已拥有的等级保留。",
            "max": "该部件已满级5-2。",
            "request_conflict": "这条消息已处理过其他升级，请重新发送指令。",
            "insufficient_balance": f"余额不足，还差 {result.get('shortage')} {currency}。",
        }.get(status, "操作失败，请稍后重试。")
    if command == "/购买装备":
        item = next((r for r in shop["items"] if r["number"] == int(parts[1])), None)
        if item is None:
            return "部件编号不存在，请发送 /工位背包 查看。"
        if item['bundled']:
            return '五项基础布置已随环境配套拥有，无需购买；更换整套环境请发送 /升级工位。'
        return (f"当前环境基础档已拥有，无需购买。#{item['number']} {item['category']}已有等级保留。\n"
                "每个环境只有基础档、升级档；升级使用 /升级装备 编号。")
    if command == "/装备商城":
        all_items = len(parts) == 2
        lines = ["【工位商店】"]
        environment_item = next(r for r in shop["items"] if r['bundled'])
        advance_offer = shop['growth_offers']['advance']
        environment_status = '未满足' if advance_offer['status'] != 'available' else '可升级'
        lines.append(f"1 办公环境： Lv.{environment_item['environment']}-1→{environment_item['environment']}-2 · {environment_status}")
        items = [r for r in shop["items"] if not r['bundled'] and (all_items or r["status"] in {'available','environment_max'})]
        if not all_items:
            items.sort(key=lambda item: SHOP_DEVICE_ORDER.index(item['number']) if item['number'] in SHOP_DEVICE_ORDER else len(SHOP_DEVICE_ORDER))
        for r in items:
            if not all_items and r['number'] in SHOP_DEVICE_ORDER:
                lines.append(shop_device_line(r, currency))
                continue
            if r["status"] == 'environment_max':
                lines.append(shop_device_line(r, currency))
                continue
            if r['status'] == 'legacy_mixed':
                lines.append(f"{r['number']} {r['category']} · 旧搭配待整套升级")
                continue
            state = (f" · 还差 {r['shortage']} {currency}" if r["status"] == "insufficient_balance" else
                     f" · 需要{r['required_rank']}" if r["status"] == "rank_locked" else "")
            lines.append(f"{SHOP_DISPLAY_NUMBER.get(r['number'], r['number'])} {r['category']} · 环境{r['environment']} 基础档→升级档 · {r['next_name']} · {r['price']}{currency}{state}")
        if not items:
            lines.append("当前暂无可升级部件。")
        lines.extend(growth_prices(shop))
        return "\n".join(lines)
    progression = repository.get_workstation(employee.id)["progression"]
    components = progression["components"]
    equipped = [r for r in components if r["equipped"]]
    if command == '/工位背包':
        growth = progression['growth']
        lines = [f'【{employee.display_name}的工位背包】', '【环境】']
        for env in range(1, growth['switchable_environment'] + 1):
            lines.append(f"{env}级 {environment_name(env, rules=repository.workstation_rules())}" + ('【当前】' if env == growth['active_environment'] else ''))
        lines += ['', '【设备】']
        for r in components:
            if r['number'] >= 6:
                current = level_label(r['active_level']) if r['equipped'] else '未装备'
                lines.append(f"{r['category']}：已拥有1-1至{level_label(r['highest_level'])}｜当前{current}")
        lines += ['', '/装备 鼠标 2-1', '/装备 环境 1']
        return '\n'.join(lines)
    game_url = None if workstation_links is None else workstation_links.game_url
    url = None if workstation_links is None else game_url or workstation_links.url_for(employee.id)
    environment = progression['growth']['active_environment']
    environment_income = sum(r['daily_income'] for r in equipped if r['number'] <= 5)
    devices = [f"{r['category']}：{(r['active_level'] + 1) // 2}-{2 if r['active_level'] % 2 == 0 else 1}"
               f" {r['name']}【日收益：{r['daily_income']}】"
               for r in equipped if r['number'] >= 6]
    overview = "\n".join((f"【{employee.display_name}的工位】",
        f"环境：{str(environment) + '级 ' + environment_name(environment, rules=repository.workstation_rules()) if environment else '混合搭配'}【日收益：{environment_income}】",
        "【设备】", *(devices or ["暂无"]),
        f"预计工位日收入：{progression['daily_income']} {currency}。",
        "工位游戏卡将在下一条消息发送。" if url and workstation_links.game_card_id else
        "工位链接将在下一条消息发送。" if url else "工位网页暂未开放，请管理员配置公开访问地址。"))
    return [overview, url] if url else overview
