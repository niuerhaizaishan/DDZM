from __future__ import annotations

import re
from collections.abc import Sequence


_GUILD_MATCH_START = re.compile(r"/记忆考核\s+公会赛\s+(\d+)")
_SERIES_COMMAND = re.compile(r"/第([1-9]\d*)场\s+([1-9]\d*)/([1-9]\d*)")
_TEAM_COMMAND = re.compile(r"/队伍([12])(人员)?\s+(.+)")
_ROSTER_SEPARATOR = re.compile(r"[，,、]")
_CHINESE_DIGITS = "零一二三四五六七八九"


def parse_guild_match_start(content: str) -> int | None:
    matched = _GUILD_MATCH_START.fullmatch(_normalize_spaces(content))
    if matched is None:
        return None
    planned_series_count = int(matched.group(1))
    return planned_series_count if 1 <= planned_series_count <= 20 else None


def parse_series_command(content: str) -> tuple[int, int, int] | None:
    matched = _SERIES_COMMAND.fullmatch(_normalize_spaces(content))
    if matched is None:
        return None
    sequence, win_target, maximum_decisive_rounds = map(int, matched.groups())
    if (
        maximum_decisive_rounds > 99
        or maximum_decisive_rounds % 2 == 0
        or win_target * 2 != maximum_decisive_rounds + 1
    ):
        return None
    return sequence, win_target, maximum_decisive_rounds


def parse_team_command(content: str) -> tuple[int, str, str] | None:
    matched = _TEAM_COMMAND.fullmatch(_normalize_spaces(content))
    if matched is None:
        return None
    slot = int(matched.group(1))
    field = "members" if matched.group(2) else "name"
    value = matched.group(3).strip()
    return (slot, field, value) if value else None


def split_roster_names(value: str) -> tuple[str, ...]:
    names = tuple(part.strip() for part in _ROSTER_SEPARATOR.split(value) if part.strip())
    if not names:
        raise ValueError("队伍人员不能为空")
    if len(set(names)) != len(names):
        raise ValueError("队伍人员不能重复")
    return names


def render_guild_match_created(host_name: str, planned_series_count: int) -> str:
    return "\n".join(
        (
            "━━━━━━━━━━━━━━",
            "🏆 记忆考核 · 公会赛",
            "━━━━━━━━━━━━━━",
            f"🎙️ 主持人：{host_name}",
            "",
            "🔴 队伍1：等待配置",
            "🔵 队伍2：等待配置",
            "",
            f"📋 预设场次：{planned_series_count}场",
            "⚔️ 当前大比分：0 : 0",
            "━━━━━━━━━━━━━━",
        )
    )


def render_guild_series_ready(
    *,
    sequence: int,
    win_target: int,
    maximum_decisive_rounds: int,
    team1_player: str,
    team2_player: str,
    team1_wins: int,
    team2_wins: int,
    next_round_sequence: int,
) -> str:
    return "\n".join(
        (
            "━━━━━━━━━━━━━━",
            (
                f"⚔️ 第{sequence}场 · "
                f"{_chinese_number(maximum_decisive_rounds)}局"
                f"{_chinese_number(win_target)}胜"
            ),
            "━━━━━━━━━━━━━━",
            f"🔴 {team1_player}",
            "        VS",
            f"🔵 {team2_player}",
            "",
            f"🧠 当前小局：第{next_round_sequence}局",
            f"📊 本场比分：{team1_wins} : {team2_wins}",
            "🎙️ 请主持人发送 /开始对战",
            "━━━━━━━━━━━━━━",
        )
    )


def render_guild_round_result(
    *,
    series_sequence: int,
    round_sequence: int,
    winner_name: str | None,
    team1_wins: int,
    team2_wins: int,
) -> str:
    outcome = (
        f"✅ {winner_name} 赢得本局" if winner_name is not None else "🤝 本局平局"
    )
    return "\n".join(
        (
            "━━━━━━━━━━━━━━",
            f"🧠 第{series_sequence}场 · 第{round_sequence}局",
            "━━━━━━━━━━━━━━",
            outcome,
            f"📊 本场比分：{team1_wins} : {team2_wins}",
            "━━━━━━━━━━━━━━",
        )
    )


def render_guild_match_finished(
    *,
    champion_name: str,
    team1_score: int,
    team2_score: int,
    series_lines: Sequence[str],
) -> str:
    return "\n".join(
        (
            "━━━━━━━━━━━━━━",
            "🏆 公会赛结束",
            "━━━━━━━━━━━━━━",
            f"👑 冠军：{champion_name}",
            f"📊 最终大比分：{team1_score} : {team2_score}",
            "",
            *(f"⚔️ {line}" for line in series_lines),
            "",
            f"✨ 恭喜{champion_name}赢得本次公会赛！",
            "━━━━━━━━━━━━━━",
        )
    )


def _normalize_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def _chinese_number(value: int) -> str:
    if value < 10:
        return _CHINESE_DIGITS[value]
    tens, ones = divmod(value, 10)
    prefix = "十" if tens == 1 else f"{_CHINESE_DIGITS[tens]}十"
    return prefix if ones == 0 else f"{prefix}{_CHINESE_DIGITS[ones]}"
