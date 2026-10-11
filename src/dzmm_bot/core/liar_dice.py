"""大话骰子（吹牛骰）判定引擎 —— 纯函数，与存储和指令层解耦。

规则：
- 每人 5 个骰子（1-6 点）
- 每轮随机一个 1~6 的点数作为「万能点」，公布到群里；开牌时万能点可顶任何点数
- 一旦有人叫过「N 个万能点」，万能点失效，只算它自己的点数
- 轮流叫「N 个 X」；下家加码或开牌
- 加码：N' > N 或 (N' = N 且 X' > X)，点数 1 < 2 < … < 6
- 首叫 N ≥ 在场人数
- 开牌：实际 X 数量（含有效万能点）≥ N → 叫的人赢，否则开牌的人赢
"""
import random
import re

DIE_FACES = (1, 2, 3, 4, 5, 6)
DICE_PER_PLAYER = 5

DIE_EMOJI = {1: "🎲1", 2: "🎲2", 3: "🎲3", 4: "🎲4", 5: "🎲5", 6: "🎲6"}

_CALL_PATTERN = re.compile(r"^/?(?P<count>\d+)\s*个\s*(?P<face>[1-6])$")


def roll_dice(rng: random.Random, count: int = DICE_PER_PLAYER) -> list[int]:
    return [rng.randint(1, 6) for _ in range(count)]


def roll_wild(rng: random.Random) -> int:
    return rng.randint(1, 6)


def dice_str(dice: list[int]) -> str:
    return " ".join(DIE_EMOJI.get(face, str(face)) for face in dice)


def wild_note(wild_face: int, invalidated: bool, *, verbose: bool = True) -> str:
    """万能点提示的唯一来源（发骰私聊 / 看骰 / 开局公告 / 牌局四处共用）。

    历史上这几处文案各写各的，结果「私聊发骰」那处漏掉了万能点。
    """
    if invalidated:
        return f"⚠️ 本轮万能点 {dice_str([wild_face])} 已被叫过，不再生效"
    if verbose:
        return (
            f"🃏 本轮万能点：{dice_str([wild_face])}"
            "（可顶任何点数；有人叫过它之后失效）"
        )
    return f"🃏 本轮万能点：{dice_str([wild_face])}（可顶任何点数）"


def count_point(
    all_dice: dict[str, list[int]],
    face: int,
    wild: int,
    called_wild: bool,
) -> int:
    """统计全场 face 的数量（含有效万能点）。

    all_dice: {platform_id: [骰子点数]}；called_wild 为 True 时万能点失效只算自身。
    """
    total = 0
    for dice in all_dice.values():
        for value in dice:
            if value == face:
                total += 1
            elif value == wild and not called_wild and face != wild:
                total += 1
    return total


def is_legal_raise(
    old: tuple[int, int] | None,
    new: tuple[int, int],
    player_count: int,
) -> bool:
    """加码合法性；old 为 None 表示首叫（N ≥ 在场人数）。"""
    new_count, new_face = new
    if new_count < 1 or new_face not in DIE_FACES:
        return False
    if old is None:
        return new_count >= player_count
    old_count, old_face = old
    if new_count > old_count:
        return True
    return new_count == old_count and new_face > old_face


def judge_open(
    all_dice: dict[str, list[int]],
    call: tuple[int, int],
    wild: int,
    called_wild: bool,
) -> bool:
    """开牌判定；返回 True 表示叫数方赢，False 表示开牌方赢。"""
    actual = count_point(all_dice, call[1], wild, called_wild)
    return actual >= call[0]


def parse_call(text: str) -> tuple[int, int] | None:
    """解析叫数文本，如 '3个3' / '/5个6' → (3, 3) / (5, 6)；非法返回 None。"""
    match = _CALL_PATTERN.match(text.strip())
    if match is None:
        return None
    return int(match.group("count")), int(match.group("face"))
