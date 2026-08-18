from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


NUMBER_BOMB_MULTIPLIER_TENTHS = (8, 9, 10, 11, 12)
POINTS_TOURNAMENT_SCORES = {1: 10, 2: 5, 3: 0, 4: 0, 5: 0, 6: 0, 7: -3, 8: 2}


@dataclass(frozen=True)
class NumberBombEntry:
    platform_id: str
    display_name: str
    number: int
    display_order: int


@dataclass(frozen=True)
class NumberBombStanding:
    entry: NumberBombEntry
    deviation_numerator: int
    result: str | None


@dataclass(frozen=True)
class NumberBombCalculation:
    total: int
    player_count: int
    multiplier_tenths: int
    target_numerator: int
    target_denominator: int
    standings: tuple[NumberBombStanding, ...]
    valid: bool


@dataclass(frozen=True)
class NumberBombPointsPlayer:
    platform_id: str
    rank: int | None
    points: int
    absent: bool


@dataclass(frozen=True)
class NumberBombPointsResult:
    players: tuple[NumberBombPointsPlayer, ...]


def calculate_number_bomb(
    entries: Sequence[NumberBombEntry],
    multiplier_tenths: int,
) -> NumberBombCalculation:
    player_count = len(entries)
    if player_count == 0:
        raise ValueError("at least one entry is required")
    if (
        isinstance(multiplier_tenths, bool)
        or not isinstance(multiplier_tenths, int)
        or multiplier_tenths not in NUMBER_BOMB_MULTIPLIER_TENTHS
    ):
        raise ValueError("蹦蹦数字炸弹倍率必须是 0.8 至 1.2 的允许值")
    total = sum(entry.number for entry in entries)
    target_numerator = multiplier_tenths * total
    target_denominator = 10 * player_count
    deviations = tuple(
        (
            entry,
            abs(target_denominator * entry.number - target_numerator),
        )
        for entry in entries
    )
    bands = sorted({deviation for _, deviation in deviations}, reverse=True)
    valid = len(bands) >= 3
    punished_band = bands[1] if valid else None
    winner_band = bands[-1] if valid else None

    standings = tuple(
        NumberBombStanding(
            entry=entry,
            deviation_numerator=deviation,
            result=(
                "punished"
                if deviation == punished_band
                else "winner"
                if deviation == winner_band
                else "neutral"
                if valid
                else None
            ),
        )
        for entry, deviation in sorted(
            deviations,
            key=lambda item: (-item[1], item[0].display_order),
        )
    )
    return NumberBombCalculation(
        total=total,
        player_count=player_count,
        multiplier_tenths=multiplier_tenths,
        target_numerator=target_numerator,
        target_denominator=target_denominator,
        standings=standings,
        valid=valid,
    )


def calculate_points_tournament_scores(
    calculation: NumberBombCalculation,
    absent_player_ids: Sequence[str],
) -> NumberBombPointsResult:
    reported = tuple(
        sorted(
            calculation.standings,
            key=lambda standing: (
                standing.deviation_numerator,
                standing.entry.display_order,
            ),
        )
    )
    last_deviation = max(
        (standing.deviation_numerator for standing in reported),
        default=None,
    )
    first_deviation = min(
        (standing.deviation_numerator for standing in reported),
        default=None,
    )

    def competition_rank(standing: NumberBombStanding) -> int:
        if standing.deviation_numerator == first_deviation:
            return 1
        if standing.deviation_numerator == last_deviation:
            return len(reported)
        return 1 + sum(
            other.deviation_numerator < standing.deviation_numerator
            for other in reported
        )

    players = []
    for standing in reported:
        rank = competition_rank(standing)
        players.append(
            NumberBombPointsPlayer(
                platform_id=standing.entry.platform_id,
                rank=rank,
                points=POINTS_TOURNAMENT_SCORES.get(rank, 0),
                absent=False,
            )
        )
    players.extend(
        NumberBombPointsPlayer(platform_id, None, -3, True)
        for platform_id in absent_player_ids
    )
    return NumberBombPointsResult(tuple(players))


def render_number_bomb_result(
    round_number: int,
    punishment_type: str,
    calculation: NumberBombCalculation,
) -> str:
    punishment = {"truth": "真心话", "dare": "大冒险"}[punishment_type]
    entries = sorted(
        (standing.entry for standing in calculation.standings),
        key=lambda entry: entry.display_order,
    )
    lines = [
        f"第 {round_number} 轮 - {punishment}",
        "1. 计算过程",
        *[f"{entry.display_name}：{entry.number}" for entry in entries],
        f"总和：{calculation.total}",
        f"人数：{calculation.player_count}",
        f"平均值：{_decimal(calculation.total, calculation.player_count)}",
        f"本轮随机倍率：×{_multiplier(calculation.multiplier_tenths)}",
        (
            "最终数 F：平均值 × "
            f"{_multiplier(calculation.multiplier_tenths)} = "
            f"{_decimal(calculation.target_numerator, calculation.target_denominator)}"
        ),
        "2. 偏离值排序（从大到小）",
    ]
    for standing in calculation.standings:
        annotation = ""
        if standing.result == "punished":
            annotation = "（第二大偏离 → 受罚者）"
        elif standing.result == "winner":
            annotation = "（最小偏离 → 胜出者）"
        lines.append(
            f"{standing.entry.display_name}：{standing.entry.number}，"
            f"偏离值 {_decimal(standing.deviation_numerator, calculation.target_denominator)}"
            f"{annotation}"
        )
    lines.append("3. 最终游戏结果")
    if not calculation.valid:
        lines.append("本轮偏离值不足三个不同档位，本轮无效，请所有参与者重新私聊报数。")
        return "\n".join(lines)

    winners = _result_names(calculation, "winner")
    punished = _result_names(calculation, "punished")
    lines.extend(
        [
            f"胜出者：{winners}",
            f"受罚者：{punished}",
            f"本轮为{punishment}轮，由胜出者出题并监督，受罚者必须完成对应的惩罚。",
        ]
    )
    return "\n".join(lines)


def _result_names(calculation: NumberBombCalculation, result: str) -> str:
    selected = sorted(
        (
            standing.entry
            for standing in calculation.standings
            if standing.result == result
        ),
        key=lambda entry: entry.display_order,
    )
    return "、".join(
        f"{entry.display_name}（{entry.number}）" for entry in selected
    )


def _decimal(numerator: int, denominator: int) -> str:
    value = Decimal(numerator) / Decimal(denominator)
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _multiplier(multiplier_tenths: int) -> str:
    return f"{multiplier_tenths // 10}.{multiplier_tenths % 10}"
