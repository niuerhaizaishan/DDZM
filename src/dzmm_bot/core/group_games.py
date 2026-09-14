from collections.abc import Sequence
from typing import Literal, TypeAlias


GroupGameType: TypeAlias = Literal[
    "red_packet",
    "hide_and_seek",
    "memory_assessment",
    "undercover",
    "blame_bomb",
    "number_bomb",
    "texas_holdem",
    "never_have_i_ever",
    "king_game",
]

GROUP_GAME_TYPES: tuple[GroupGameType, ...] = (
    "red_packet",
    "hide_and_seek",
    "memory_assessment",
    "undercover",
    "blame_bomb",
    "number_bomb",
    "texas_holdem",
    "never_have_i_ever",
    "king_game",
)

GROUP_GAME_LABELS: dict[GroupGameType, str] = {
    "red_packet": "发红包",
    "hide_and_seek": "摸鱼躲猫猫",
    "memory_assessment": "记忆考核",
    "undercover": "谁是卧底",
    "blame_bomb": "甩锅游戏",
    "number_bomb": "蹦蹦数字炸弹",
    "texas_holdem": "德州扑克",
    "never_have_i_ever": "我有你没有",
    "king_game": "国王游戏",
}

GROUP_GAME_COMMANDS: dict[str, GroupGameType] = {
    "/发红包": "red_packet",
    "/抢红包": "red_packet",
    "/摸鱼躲猫猫": "hide_and_seek",
    "/记忆考核": "memory_assessment",
    "/收手": "memory_assessment",
    "/投降": "memory_assessment",
    "/谁是卧底": "undercover",
    "/开始投票": "undercover",
    "/投票": "undercover",
    "/退出谁是卧底": "undercover",
    "/甩锅游戏": "blame_bomb",
    "/甩锅": "blame_bomb",
    "/退出甩锅": "blame_bomb",
    "/蹦蹦数字炸弹": "number_bomb",
    "/报数": "number_bomb",
    "/德州扑克": "texas_holdem",
    "/看牌": "texas_holdem",
    "/过牌": "texas_holdem",
    "/跟注": "texas_holdem",
    "/加注": "texas_holdem",
    "/全下": "texas_holdem",
    "/弃牌": "texas_holdem",
    "/我有你没有": "never_have_i_ever",
    "/发言": "never_have_i_ever",
    "/扣": "never_have_i_ever",
    "/不扣": "never_have_i_ever",
    "/国王游戏": "king_game",
    "/国王游戏数据": "king_game",
    "/公开": "king_game",
}


def normalized_group_game_types(values: Sequence[str]) -> tuple[GroupGameType, ...]:
    if any(value not in GROUP_GAME_TYPES for value in values):
        raise ValueError("invalid group game type")
    return tuple(value for value in GROUP_GAME_TYPES if value in values)
