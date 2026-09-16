"""随机事件投票：纯逻辑层。

不碰数据库，只做三件事：

1. `tiered_pool` 按既有随机逻辑把候选池分成三档
   （没演过且没排过 → 演过但没排过 → 今天已排过）；
2. `pick_tiered` 按档抽取 N 个互不相同的场景（第一档不够才跨档补）；
3. `break_tie` / `tally` 负责平票判定与计票。

`tiered_pool` 与 `repository._fill_random_event_schedule_snapshot` 表达的是同一套
优先规则——两边不会漂。
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import UUID

T = TypeVar("T")

#: 与仓储层共用的随机源签名（`secrets.randbelow`）
Randbelow = Callable[[int], int]


def tiered_pool(
    scenes: Sequence[str],
    *,
    performed: Collection[str],
    planned: Collection[str],
    exclude: Collection[str] = (),
) -> list[list[str]]:
    """把场景名分成三档，越靠前的档越该被选中。

    依次是「没演过且没排过」「演过但没排过」「今天已排过」——与既有随机逻辑
    一致；区别只在于既有逻辑是**只取命中的那一档**，而这里把三档都留下，让调用
    方能在第一档不够时按档补齐。

    **必须保留档位边界**：如果拍平成一个列表再随机抽，第一档有货也可能抽到
    第三档，优先规则就白写了。
    """
    excluded = set(exclude)
    seen: set[str] = set()
    tiers: list[list[str]] = [[], [], []]
    for name in scenes:
        if name in excluded or name in seen:
            continue
        seen.add(name)
        if name in planned:
            tiers[2].append(name)
        elif name in performed:
            tiers[1].append(name)
        else:
            tiers[0].append(name)
    return tiers


def flatten_tiers(tiers: Sequence[Sequence[T]]) -> list[T]:
    """把分档拍平成一列（只用于展示或断言，抽取不要用它）。"""
    return [item for tier in tiers for item in tier]


def pick_tiered(
    tiers: Sequence[Sequence[T]], count: int, randbelow: Randbelow
) -> list[T]:
    """按档抽取：先把第一档抽满，不够再从第二档补，以此类推。"""
    if count <= 0:
        return []
    picked: list[T] = []
    for tier in tiers:
        if len(picked) >= count:
            break
        picked.extend(pick_distinct(tier, count - len(picked), randbelow))
    return picked


def pick_distinct(pool: Sequence[T], count: int, randbelow: Randbelow) -> list[T]:
    """从池子里随机抽 `count` 个互不相同的元素；池子不够就全给。"""
    if count <= 0:
        return []
    remaining = list(pool)
    picked: list[T] = []
    while remaining and len(picked) < count:
        picked.append(remaining.pop(randbelow(len(remaining))))
    return picked


def break_tie(
    candidate_ids: Sequence[UUID],
    *,
    performances: Mapping[UUID, int],
    authored_at: Mapping[UUID, datetime],
    randbelow: Randbelow,
) -> UUID:
    """平票三级判定：演出次数少 → 投稿晚 → 随机。

    `authored_at` 传"这个作品的时间"：有投稿的用 `submitted_at`，后台自建场景
    没有投稿记录，退化为场景的 `created_at`（两者统一比较）。
    """
    if not candidate_ids:
        raise ValueError("平票判定至少需要一个候选")
    fewest = min(performances.get(candidate, 0) for candidate in candidate_ids)
    least_performed = [
        candidate
        for candidate in candidate_ids
        if performances.get(candidate, 0) == fewest
    ]
    if len(least_performed) == 1:
        return least_performed[0]

    latest = max(authored_at[candidate] for candidate in least_performed)
    newest = [
        candidate
        for candidate in least_performed
        if authored_at[candidate] == latest
    ]
    if len(newest) == 1:
        return newest[0]
    return newest[randbelow(len(newest))]


def tally(candidate_ids: Sequence[UUID], votes: Iterable[UUID]) -> dict[UUID, int]:
    """计票：每个候选都有计数（没人投就是 0），方便直接渲染票型。"""
    counts = {candidate: 0 for candidate in candidate_ids}
    for candidate in votes:
        if candidate in counts:
            counts[candidate] += 1
    return counts


def top_candidates(counts: Mapping[UUID, int]) -> list[UUID]:
    """得票最高的候选（可能并列）；全为 0 时返回空列表。"""
    if not counts:
        return []
    highest = max(counts.values())
    if highest <= 0:
        return []
    return [
        candidate for candidate, count in counts.items() if count == highest
    ]
