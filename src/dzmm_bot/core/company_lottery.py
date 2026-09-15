"""公司双色球：纯逻辑层。

号码生成、判档、奖池结算、全员福利判定与购票指令解析。
所有函数均为纯函数，不读写数据库、不依赖会话。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from math import comb
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")

SECONDS_PER_DAY = 86_400
IDLE_SECONDS_BEFORE_NOTIFY = 1_800

DEFAULT_RED_POOL = 10
DEFAULT_RED_COUNT = 4
DEFAULT_BLUE_POOL = 6
DEFAULT_TICKET_PRICE = 2
DEFAULT_POOL_CEILING = 200
DEFAULT_PER_PERSON_CAP = 100
DEFAULT_MAX_TICKETS_PER_DAY = 5
DEFAULT_WELFARE_PER_PERSON = 1
DEFAULT_POOL_SEED = 100


class PrizeTier(StrEnum):
    HEAD = "head"
    SECOND = "second"
    THIRD = "third"
    FOURTH = "fourth"
    FIFTH = "fifth"


ALL_TIERS: tuple[PrizeTier, ...] = (
    PrizeTier.HEAD,
    PrizeTier.SECOND,
    PrizeTier.THIRD,
    PrizeTier.FOURTH,
    PrizeTier.FIFTH,
)

DEFAULT_PRIZES: dict[PrizeTier, int] = {
    PrizeTier.HEAD: 100,
    PrizeTier.SECOND: 50,
    PrizeTier.THIRD: 15,
    PrizeTier.FOURTH: 5,
    PrizeTier.FIFTH: 1,
}


class OrderKind(StrEnum):
    MANUAL = "manual"
    QUICK = "quick"
    GUIDED = "guided"


QUICK_ALIASES: frozenset[str] = frozenset({"机选", "随机", "机", "random", "quick"})
COMMAND_ALIASES: dict[str, str] = {"买彩票": "购买彩票"}

# 余额流水的来源用稳定 token（与红包、德州扑克一致），中文标签在仓储层的
# _BALANCE_SOURCE_LABELS 里；这样「今日收益」与收益榜才能按来源过滤掉彩票。
LOTTERY_PURCHASE_SOURCE = "company_lottery_purchase"
LOTTERY_PRIZE_SOURCE = "company_lottery_prize"
LOTTERY_WELFARE_SOURCE = "company_lottery_welfare"
LOTTERY_BALANCE_SOURCES: frozenset[str] = frozenset(
    {LOTTERY_PURCHASE_SOURCE, LOTTERY_PRIZE_SOURCE, LOTTERY_WELFARE_SOURCE}
)

_SPLIT = re.compile(r"[\s,+，]+")


@dataclass(frozen=True)
class Ticket:
    """一注号码。红球按升序保存，保证同一组号码只有一种写法。"""

    reds: tuple[int, ...]
    blue: int

    def as_key(self) -> str:
        reds = "|".join(f"{number:02d}" for number in self.reds)
        return f"{reds}+{self.blue:02d}"

    def display(self) -> str:
        reds = "  ".join(f"{number:02d}" for number in self.reds)
        markers = "🔴" * len(self.reds)
        return f"{markers}　{reds}　　🔵 {self.blue:02d}"


class TicketParseError(ValueError):
    """购票指令解析失败，携带场景码供文案选择。"""

    def __init__(self, scenario: str, detail: str = "") -> None:
        super().__init__(detail or scenario)
        self.scenario = scenario
        self.detail = detail


@dataclass(frozen=True)
class Order:
    kind: OrderKind
    quantity: int = 1
    ticket: Ticket | None = None


@dataclass(frozen=True)
class RoundSettlement:
    pool_opening: int
    sales: int
    overflow: int
    pool_available: int
    payable: int
    haircut: Decimal | None
    paid_total: int
    pool_closing: int
    per_user: dict[str, int]
    per_user_paid: dict[str, int]
    capped_users: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WelfareCheck:
    triggered: bool
    employee_count: int
    fund_before: int
    fund_after: int
    per_person: int
    paid_total: int


def verify_round_conservation(settlement: RoundSettlement) -> None:
    """奖池守恒：期初 + 本期售票 = 溢出转出 + 实付派奖 + 奖池期末。

    彩票是唯一「有系统净注入、奖池跨期滚存、还分两本账」的玩法，一旦结算或账本
    写入出错，摸鱼币会静默消失或多出来，所以这里做成硬断言而不是只显示数字。
    """
    if (
        settlement.pool_opening + settlement.sales
        != settlement.overflow + settlement.paid_total + settlement.pool_closing
    ):
        raise RuntimeError(
            "公司双色球奖池不守恒："
            f"期初 {settlement.pool_opening} + 售票 {settlement.sales} != "
            f"溢出 {settlement.overflow} + 派奖 {settlement.paid_total} + "
            f"期末 {settlement.pool_closing}"
        )
    if sum(settlement.per_user_paid.values()) != settlement.paid_total:
        raise RuntimeError("公司双色球员工侧派奖合计与实付不一致")


def verify_welfare_conservation(check: WelfareCheck) -> None:
    """福利守恒：调节金发放前 = 发放额 + 剩余，且发放额按人头整除。"""
    if check.fund_before != check.paid_total + check.fund_after:
        raise RuntimeError("公司双色球调节金不守恒")
    if check.triggered and check.employee_count * check.per_person != check.paid_total:
        raise RuntimeError("公司双色球福利发放额与人数不一致")


def draw_numbers(*, red_pool: int = DEFAULT_RED_POOL,
                 red_count: int = DEFAULT_RED_COUNT,
                 blue_pool: int = DEFAULT_BLUE_POOL) -> Ticket:
    """无放回抽取红球，独立抽取蓝球。"""
    reds = tuple(sorted(secrets.SystemRandom().sample(range(1, red_pool + 1), red_count)))
    return Ticket(reds=reds, blue=secrets.randbelow(blue_pool) + 1)


def commit_hash(ticket: Ticket, salt: str) -> str:
    payload = f"{ticket.as_key()}|{salt}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def new_salt() -> str:
    return secrets.token_hex(16)


def quick_tickets(*, quantity: int,
                  red_pool: int = DEFAULT_RED_POOL,
                  red_count: int = DEFAULT_RED_COUNT,
                  blue_pool: int = DEFAULT_BLUE_POOL,
                  exclude: Iterable[str] | None = None,
                  guard_factor: int = 100) -> list[Ticket]:
    """机选若干注，注间互不重复，并避开 exclude 中已占用的号码。"""
    if quantity < 1:
        raise ValueError("quantity must be positive")

    taken = set(exclude or ())
    picked: list[Ticket] = []
    attempts = 0
    limit = quantity * guard_factor

    while len(picked) < quantity:
        attempts += 1
        if attempts > limit:
            raise RuntimeError("机选空间不足，无法生成互不重复的号码")
        ticket = draw_numbers(red_pool=red_pool, red_count=red_count,
                              blue_pool=blue_pool)
        key = ticket.as_key()
        if key in taken:
            continue
        taken.add(key)
        picked.append(ticket)

    return picked


def is_quick_pick(content: str) -> bool:
    return content.strip() in QUICK_ALIASES


def judge(answer: Ticket, ticket: Ticket) -> PrizeTier | None:
    """判定档位。红球顺序无关。"""
    red_hits = len(set(answer.reds) & set(ticket.reds))
    blue_hit = answer.blue == ticket.blue

    if red_hits == 4 and blue_hit:
        return PrizeTier.HEAD
    if red_hits == 4:
        return PrizeTier.SECOND
    if red_hits == 3 and blue_hit:
        return PrizeTier.THIRD
    if red_hits == 3:
        return PrizeTier.FOURTH
    if blue_hit:
        return PrizeTier.FIFTH
    return None


def tier_counts(*, red_pool: int = DEFAULT_RED_POOL,
                red_count: int = DEFAULT_RED_COUNT,
                blue_pool: int = DEFAULT_BLUE_POOL) -> dict[PrizeTier | None, int]:
    """各档位组合数，含 None（未中）。合计等于总组合数。"""
    missing = red_pool - red_count
    red_hits = {
        hits: comb(red_count, hits) * comb(missing, red_count - hits)
        for hits in range(red_count + 1)
    }

    counts: dict[PrizeTier | None, int] = {
        PrizeTier.HEAD: red_hits[4] * 1,
        PrizeTier.SECOND: red_hits[4] * (blue_pool - 1),
        PrizeTier.THIRD: red_hits[3] * 1,
        PrizeTier.FOURTH: red_hits[3] * (blue_pool - 1),
        PrizeTier.FIFTH: (red_hits[2] + red_hits[1] + red_hits[0]) * 1,
    }
    counts[None] = total_combinations(
        red_pool=red_pool, red_count=red_count, blue_pool=blue_pool
    ) - sum(counts.values())
    return counts


def total_combinations(*, red_pool: int = DEFAULT_RED_POOL,
                       red_count: int = DEFAULT_RED_COUNT,
                       blue_pool: int = DEFAULT_BLUE_POOL) -> int:
    return comb(red_pool, red_count) * blue_pool


def winning_combinations(*, red_pool: int = DEFAULT_RED_POOL,
                         red_count: int = DEFAULT_RED_COUNT,
                         blue_pool: int = DEFAULT_BLUE_POOL) -> int:
    counts = tier_counts(red_pool=red_pool, red_count=red_count,
                         blue_pool=blue_pool)
    return sum(counts[tier] for tier in ALL_TIERS)


def expected_return(prizes: Mapping[PrizeTier, int],
                    *, red_pool: int = DEFAULT_RED_POOL,
                    red_count: int = DEFAULT_RED_COUNT,
                    blue_pool: int = DEFAULT_BLUE_POOL) -> Decimal:
    """每注期望返回，用于校验返奖率。"""
    counts = tier_counts(red_pool=red_pool, red_count=red_count,
                         blue_pool=blue_pool)
    total = Decimal(total_combinations(red_pool=red_pool, red_count=red_count,
                                       blue_pool=blue_pool))
    return sum(
        Decimal(counts[tier]) * Decimal(prizes[tier]) / total for tier in ALL_TIERS
    )


def settle_round(*, pool_opening: int, sales: int,
                 winners: Sequence[tuple[str, PrizeTier]],
                 prizes: Mapping[PrizeTier, int],
                 per_person_cap: int = DEFAULT_PER_PERSON_CAP,
                 pool_ceiling: int = DEFAULT_POOL_CEILING) -> RoundSettlement:
    """结算一期奖池。

    顺序固定：投注额入池 → 奖池封顶溢出 → 按员工合并 → 合并后封顶 →
    可付款不足时折算 → 发放。折算发生在封顶之后。
    """
    pool = pool_opening + sales
    overflow = max(0, pool - pool_ceiling)
    pool_available = pool - overflow

    merged: dict[str, int] = defaultdict(int)
    for user_id, tier in winners:
        merged[user_id] += prizes[tier]

    capped_users = tuple(
        sorted(user_id for user_id, amount in merged.items() if amount > per_person_cap)
    )
    per_user = {
        user_id: min(amount, per_person_cap) for user_id, amount in merged.items()
    }

    payable = sum(per_user.values())
    if payable > 0 and payable > pool_available:
        haircut = (Decimal(pool_available) / Decimal(payable)).quantize(
            Decimal("0.0001"), rounding=ROUND_DOWN
        )
        per_user_paid = {
            user_id: int(Decimal(amount) * haircut)
            for user_id, amount in per_user.items()
        }
    else:
        haircut = None
        per_user_paid = dict(per_user)

    paid_total = sum(per_user_paid.values())

    return RoundSettlement(
        pool_opening=pool_opening,
        sales=sales,
        overflow=overflow,
        pool_available=pool_available,
        payable=payable,
        haircut=haircut,
        paid_total=paid_total,
        pool_closing=pool_available - paid_total,
        per_user=dict(per_user),
        per_user_paid=per_user_paid,
        capped_users=capped_users,
    )


def check_welfare(*, fund: int, employee_count: int,
                  per_person: int = DEFAULT_WELFARE_PER_PERSON) -> WelfareCheck:
    """调节金是否达到全员发放门槛。

    门槛恒为当前已注册员工总数；每次只发一轮，余数保留。
    """
    threshold = employee_count * per_person
    if employee_count <= 0 or per_person <= 0 or fund < threshold:
        return WelfareCheck(
            triggered=False,
            employee_count=employee_count,
            fund_before=fund,
            fund_after=fund,
            per_person=per_person,
            paid_total=0,
        )

    return WelfareCheck(
        triggered=True,
        employee_count=employee_count,
        fund_before=fund,
        fund_after=fund - threshold,
        per_person=per_person,
        paid_total=threshold,
    )


def round_timing(*, now: datetime, draw_hour: int, draw_minute: int,
                 close_offset_minutes: int) -> tuple[datetime, datetime]:
    """返回 (停售时刻, 开奖时刻)。已经过了今天的开奖点就顺延到明天。"""
    draw_at = now.replace(hour=draw_hour, minute=draw_minute, second=0, microsecond=0)
    if draw_at <= now:
        draw_at += timedelta(days=1)
    close_at = draw_at - timedelta(minutes=close_offset_minutes)
    return close_at, draw_at


def should_notify_close(*, now: datetime, close_at: datetime,
                        notify_offset_minutes: int,
                        seconds_since_last_message: int) -> bool:
    """停售提醒：进入提醒窗口，且群里足够冷清，避免刷屏。"""
    remaining = (close_at - now).total_seconds()
    return (
        0 < remaining <= notify_offset_minutes * 60
        and seconds_since_last_message > IDLE_SECONDS_BEFORE_NOTIFY
    )


def parse_single(content: str, *, red_pool: int = DEFAULT_RED_POOL,
                 red_count: int = DEFAULT_RED_COUNT,
                 blue_pool: int = DEFAULT_BLUE_POOL) -> Ticket:
    """解析 `/购买彩票 03 07 09 10 + 05` 形式的手选号码。

    引导购票时发的是裸号码（`03 07 09 10 + 05`），所以只在前导 token 是指令
    （以 `/` 开头）时才丢掉它，两种写法共用同一套校验。
    """
    tokens = [token for token in _SPLIT.split(content.strip()) if token]
    if tokens and tokens[0].startswith("/"):
        tokens = tokens[1:]
    if not tokens or not all(token.isdigit() for token in tokens):
        raise TicketParseError("format")

    expected = red_count + 1
    if len(tokens) != expected:
        raise TicketParseError(
            "red_count_mismatch",
            f"需要 {red_count} 个红球，你写了 {max(0, len(tokens) - 1)} 个",
        )

    numbers = [int(token) for token in tokens]
    reds, blue = numbers[:red_count], numbers[red_count]

    for number in reds:
        if not 1 <= number <= red_pool:
            raise TicketParseError(
                "red_out_of_range",
                f"红球须在 01-{red_pool:02d}，你写了 {number:02d}",
            )
    if len(set(reds)) != red_count:
        raise TicketParseError("red_duplicate", "红球不能重复")
    if not 1 <= blue <= blue_pool:
        raise TicketParseError(
            "blue_out_of_range",
            f"蓝球须在 01-{blue_pool:02d}，你写了 {blue:02d}",
        )

    return Ticket(reds=tuple(sorted(reds)), blue=blue)


def parse_order(content: str, *, red_pool: int = DEFAULT_RED_POOL,
                red_count: int = DEFAULT_RED_COUNT,
                blue_pool: int = DEFAULT_BLUE_POOL,
                max_quantity: int = DEFAULT_MAX_TICKETS_PER_DAY) -> Order:
    """解析购票指令，返回手选、机选或引导购票三种意图之一。"""
    body = [token for token in _SPLIT.split(content.strip()) if token][1:]
    if not body:
        raise TicketParseError("empty")

    if body[0] in QUICK_ALIASES:
        if len(body) > 2:
            raise TicketParseError("format")
        quantity = 1
        if len(body) == 2:
            if not body[1].isdigit():
                raise TicketParseError("format")
            quantity = int(body[1])
        if not 1 <= quantity <= max_quantity:
            raise TicketParseError("limit", f"每人每天最多 {max_quantity} 注")
        return Order(kind=OrderKind.QUICK, quantity=quantity)

    if len(body) <= 2 and body[0].isdigit():
        if len(body) == 2 and body[1] not in {"注", "buy"}:
            raise TicketParseError("format")
        quantity = int(body[0])
        if not 1 <= quantity <= max_quantity:
            raise TicketParseError("limit", f"每人每天最多 {max_quantity} 注")
        return Order(kind=OrderKind.GUIDED, quantity=quantity)

    if not body[0].isdigit():
        raise TicketParseError("format")

    ticket = parse_single(content, red_pool=red_pool, red_count=red_count,
                          blue_pool=blue_pool)
    return Order(kind=OrderKind.MANUAL, quantity=1, ticket=ticket)
