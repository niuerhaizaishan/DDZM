"""Shared public names and levels for workstation commands and clients."""
ENVIRONMENT_NAMES = ('临时办公角落', '普通办公环境', '专业办公环境', '高端办公环境', '顶级专属办公室')
DEVICE_NUMBERS = {'电脑': 6, '显示器': 7, '键盘': 8, '鼠标': 9}
RETIRED_COMMANDS = frozenset({'/工位帮助', '/工位商店', '/装备商店', '/装备商城', '/我的装备'})


def level_label(level):
    if not isinstance(level, int) or not 1 <= level <= 10:
        return '—'
    return f'{(level + 1) // 2}-{1 if level % 2 else 2}'


def parse_device_level(value):
    if len(value) == 3 and value[0] in '12345' and value[1] == '-' and value[2] in '12':
        return (int(value[0]) - 1) * 2 + int(value[2])
    if value.isascii() and value.isdecimal() and len(value) <= 2 and 1 <= int(value) <= 10:
        return int(value)
    return None
