"""Preview or explicitly apply the one-time audited S2 company reset.

The command is dry-run by default.  ``--apply`` is required for every write.
Run the Alembic migration that creates the company season audit tables first.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID, uuid4

from sqlalchemy import MetaData, Table, create_engine, delete, func, insert, inspect
from sqlalchemy import select, text, update


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dzmm_bot.core.bot_accounts import BOT_PLATFORM_IDS
from dzmm_bot.core.schema import (
    BalanceTransactionRecord,
    DarkMarketBidRecord,
    DarkMarketDeferredNoticeRecord,
    DarkMarketListingRecord,
    EquipmentItemRecord,
    EquipmentOwnershipRecord,
    ItemRecord,
    PromotionRequestRecord,
    RankRecord,
    ShopItemUseRecord,
    UserItemRecord,
    UserRecord,
    WorkstationAccessoryRecord,
    WorkstationComponentRecord,
    WorkstationRulesRecord,
)
from dzmm_bot.core.workstation_catalog import UPGRADE_COSTS
from workstation_deploy_config import database_url


SEASON_CODE = "S2"
CARRYOVER_NUMERATOR = 3
CARRYOVER_DENOMINATOR = 10
BALANCE_SOURCE = "season_reset_s2"
DARK_MARKET_ACTIVE_STATES = (
    "active",
    "awaiting_receipt",
    "complaint_pending",
)
ADVISORY_LOCK_NAMESPACE = 1_145_677_133  # ASCII-ish stable namespace for DZMM.
ADVISORY_LOCK_KEY = 2


def _json_uuid(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _validate_nonnegative(value: int, label: str) -> int:
    value = int(value)
    if value < 0:
        raise RuntimeError(f"{label} must not be negative: {value}")
    return value


def _plan_digest(plan: dict) -> str:
    """Hash every reset input while excluding generated receipt ids and timestamps."""
    payload = {
        "season_code": SEASON_CODE,
        "rules_snapshot": plan["rules_snapshot"],
        "summary": plan["summary"],
        "listing_ids": sorted(str(value) for value in plan["listing_ids"]),
        "settlements": [
            {
                key: (
                    str(value)
                    if key in {"user_id", "old_rank_id", "new_rank_id"}
                    and value is not None
                    else value
                )
                for key, value in item.items()
                if key != "id"
            }
            for item in plan["settlements"]
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workstation_cost(highest_level: int, upgrade_costs: list[int]) -> int:
    if not 1 <= highest_level <= 10:
        raise RuntimeError(f"invalid workstation level: {highest_level}")
    return sum(upgrade_costs[: highest_level - 1])


def _load_workstation_rules(connection) -> tuple[int, dict, list[int]]:
    row = connection.execute(
        select(WorkstationRulesRecord.version, WorkstationRulesRecord.data).where(
            WorkstationRulesRecord.id == 1
        )
    ).mappings().one_or_none()
    version = 0 if row is None else int(row["version"])
    data = {} if row is None else dict(row["data"])
    raw_costs = data.get("upgrade_costs", list(UPGRADE_COSTS))
    if (
        not isinstance(raw_costs, list)
        or len(raw_costs) != 9
        or any(type(value) is not int or value < 0 for value in raw_costs)
    ):
        raise RuntimeError("workstation upgrade_costs must contain 9 nonnegative integers")
    return version, data, list(raw_costs)


def _catalog_snapshot(connection) -> tuple[list[dict], list[dict], list[dict]]:
    ranks = [
        {
            "id": str(row.id),
            "sort_order": int(row.sort_order),
            "name": row.name,
            "promotion_price": int(row.promotion_price),
            "is_board": bool(row.is_board),
            "enabled": bool(row.enabled),
        }
        for row in connection.execute(
            select(
                RankRecord.id,
                RankRecord.sort_order,
                RankRecord.name,
                RankRecord.promotion_price,
                RankRecord.is_board,
                RankRecord.enabled,
            ).order_by(RankRecord.sort_order)
        )
    ]
    items = [
        {
            "id": str(row.id),
            "public_number": int(row.public_number),
            "name": row.name,
            "price": int(row.price),
            "enabled": bool(row.enabled),
            "deleted_at": None if row.deleted_at is None else row.deleted_at.isoformat(),
        }
        for row in connection.execute(
            select(
                ItemRecord.id,
                ItemRecord.public_number,
                ItemRecord.name,
                ItemRecord.price,
                ItemRecord.enabled,
                ItemRecord.deleted_at,
            ).order_by(ItemRecord.public_number)
        )
    ]
    equipment = [
        {
            "id": str(row.id),
            "public_number": int(row.public_number),
            "name": row.name,
            "price": int(row.price),
            "enabled": bool(row.enabled),
        }
        for row in connection.execute(
            select(
                EquipmentItemRecord.id,
                EquipmentItemRecord.public_number,
                EquipmentItemRecord.name,
                EquipmentItemRecord.price,
                EquipmentItemRecord.enabled,
            ).order_by(EquipmentItemRecord.public_number)
        )
    ]
    return ranks, items, equipment


def _load_plan(connection, now: datetime) -> dict:
    lv1 = connection.execute(
        select(RankRecord.id, RankRecord.name).where(RankRecord.sort_order == 1)
    ).one_or_none()
    if lv1 is None:
        raise RuntimeError("LV1 rank (sort_order=1) is missing")

    workstation_version, workstation_data, upgrade_costs = _load_workstation_rules(
        connection
    )
    rank_catalog, item_catalog, equipment_catalog = _catalog_snapshot(connection)
    for rank in rank_catalog:
        _validate_nonnegative(
            rank["promotion_price"], f"rank {rank['name']} promotion_price"
        )

    users = list(
        connection.execute(
            select(
                UserRecord.id,
                UserRecord.platform_id,
                UserRecord.display_name,
                UserRecord.balance,
                UserRecord.rank_id,
                RankRecord.name.label("rank_name"),
                RankRecord.sort_order.label("rank_sort_order"),
                RankRecord.promotion_price.label("rank_price"),
            )
            .outerjoin(RankRecord, RankRecord.id == UserRecord.rank_id)
            .order_by(UserRecord.id)
        ).mappings()
    )
    user_ids = {row["id"] for row in users}

    item_assets: dict[UUID, list[dict]] = defaultdict(list)
    for row in connection.execute(
        select(
            UserItemRecord.user_id,
            UserItemRecord.item_id,
            UserItemRecord.quantity,
            ItemRecord.public_number,
            ItemRecord.name,
            ItemRecord.price,
        )
        .join(ItemRecord, ItemRecord.id == UserItemRecord.item_id)
        .order_by(UserItemRecord.user_id, ItemRecord.public_number)
    ).mappings():
        quantity = int(row["quantity"])
        price = int(row["price"])
        if quantity > 0:
            _validate_nonnegative(price, f"item {row['name']} price")
        value = quantity * price if quantity > 0 else 0
        item_assets[row["user_id"]].append(
            {
                "item_id": str(row["item_id"]),
                "public_number": int(row["public_number"]),
                "name": row["name"],
                "quantity": quantity,
                "unit_price": price,
                "included": quantity > 0,
                "value": value,
            }
        )

    workstation_assets: dict[UUID, list[dict]] = defaultdict(list)
    for row in connection.execute(
        select(
            WorkstationComponentRecord.user_id,
            WorkstationComponentRecord.category_number,
            WorkstationComponentRecord.highest_level,
        ).order_by(
            WorkstationComponentRecord.user_id,
            WorkstationComponentRecord.category_number,
        )
    ).mappings():
        highest_level = int(row["highest_level"])
        value = _workstation_cost(highest_level, upgrade_costs)
        workstation_assets[row["user_id"]].append(
            {
                "category_number": int(row["category_number"]),
                "highest_level": highest_level,
                "value": value,
            }
        )

    equipment_assets: dict[UUID, list[dict]] = defaultdict(list)
    for row in connection.execute(
        select(
            EquipmentOwnershipRecord.user_id,
            EquipmentOwnershipRecord.item_id,
            EquipmentItemRecord.public_number,
            EquipmentItemRecord.name,
            EquipmentItemRecord.price,
        )
        .join(EquipmentItemRecord, EquipmentItemRecord.id == EquipmentOwnershipRecord.item_id)
        .order_by(EquipmentOwnershipRecord.user_id, EquipmentItemRecord.public_number)
    ).mappings():
        price = _validate_nonnegative(
            row["price"], f"equipment {row['name']} price"
        )
        equipment_assets[row["user_id"]].append(
            {
                "item_id": str(row["item_id"]),
                "public_number": int(row["public_number"]),
                "name": row["name"],
                "value": price,
            }
        )

    current_bid_rows = list(
        connection.execute(
            select(
                DarkMarketBidRecord.id.label("bid_id"),
                DarkMarketBidRecord.bidder_user_id,
                DarkMarketBidRecord.listing_id,
                DarkMarketBidRecord.amount,
                DarkMarketListingRecord.public_number,
                DarkMarketListingRecord.state.label("listing_state"),
            )
            .join(
                DarkMarketListingRecord,
                DarkMarketListingRecord.id == DarkMarketBidRecord.listing_id,
            )
            .where(DarkMarketBidRecord.state == "current")
            .order_by(DarkMarketBidRecord.id)
        ).mappings()
    )
    invalid_current_bids = [
        row
        for row in current_bid_rows
        if row["listing_state"] not in DARK_MARKET_ACTIVE_STATES
    ]
    if invalid_current_bids:
        states = sorted({row["listing_state"] for row in invalid_current_bids})
        raise RuntimeError(
            "current dark-market bids exist on terminal listings: " + ", ".join(states)
        )

    dark_market_assets: dict[UUID, list[dict]] = defaultdict(list)
    for row in current_bid_rows:
        amount = _validate_nonnegative(row["amount"], "dark-market bid amount")
        dark_market_assets[row["bidder_user_id"]].append(
            {
                "bid_id": str(row["bid_id"]),
                "listing_id": str(row["listing_id"]),
                "public_number": int(row["public_number"]),
                "listing_state": row["listing_state"],
                "value": amount,
            }
        )

    unknown_asset_users = (
        set(item_assets)
        | set(workstation_assets)
        | set(equipment_assets)
        | set(dark_market_assets)
    ) - user_ids
    if unknown_asset_users:
        raise RuntimeError("assets reference users missing from users table")

    settlements = []
    for row in users:
        rank_value = 0 if row["rank_price"] is None else _validate_nonnegative(
            row["rank_price"], "user rank price"
        )
        items = item_assets[row["id"]]
        workstation = workstation_assets[row["id"]]
        equipment = equipment_assets[row["id"]]
        bids = dark_market_assets[row["id"]]
        values = {
            "balance": int(row["balance"]),
            "rank": rank_value,
            "items": sum(item["value"] for item in items),
            "workstation": sum(item["value"] for item in workstation),
            "equipment": sum(item["value"] for item in equipment),
            "dark_market": sum(item["value"] for item in bids),
        }
        gross_value = sum(values.values())
        is_bot = row["platform_id"] in BOT_PLATFORM_IDS
        new_balance = (
            0
            if is_bot
            else max(
                0,
                gross_value * CARRYOVER_NUMERATOR // CARRYOVER_DENOMINATOR,
            )
        )
        breakdown = {
            "platform_id": row["platform_id"],
            "display_name": row["display_name"],
            "excluded_bot": is_bot,
            "values": values,
            "rank": {
                "id": _json_uuid(row["rank_id"]),
                "name": row["rank_name"],
                "sort_order": row["rank_sort_order"],
                "value": rank_value,
            },
            "items": items,
            "workstation_components": workstation,
            "equipment": equipment,
            "dark_market_bids": bids,
            "gross_value": gross_value,
            "new_balance": new_balance,
        }
        settlements.append(
            {
                "id": uuid4(),
                "user_id": row["id"],
                "is_bot": is_bot,
                "old_rank_id": row["rank_id"],
                "new_rank_id": lv1.id,
                "old_balance": int(row["balance"]),
                "gross_value": gross_value,
                "new_balance": new_balance,
                "balance_delta": new_balance - int(row["balance"]),
                "breakdown": breakdown,
            }
        )

    listing_rows = list(
        connection.execute(
            select(
                DarkMarketListingRecord.id,
                DarkMarketListingRecord.public_number,
                DarkMarketListingRecord.state,
            )
            .where(DarkMarketListingRecord.state.in_(DARK_MARKET_ACTIVE_STATES))
            .order_by(DarkMarketListingRecord.id)
        ).mappings()
    )
    listing_ids = [row["id"] for row in listing_rows]
    pending_promotions = int(
        connection.scalar(
            select(func.count())
            .select_from(PromotionRequestRecord)
            .where(PromotionRequestRecord.state == "pending")
        )
        or 0
    )
    reserved_item_uses = int(
        connection.scalar(
            select(func.count())
            .select_from(ShopItemUseRecord)
            .where(ShopItemUseRecord.state == "reserved")
        )
        or 0
    )
    if reserved_item_uses:
        raise RuntimeError(
            "reserved shop items must finish or be cancelled before the season reset"
        )
    deferred_notices = (
        0
        if not listing_ids
        else int(
            connection.scalar(
                select(func.count())
                .select_from(DarkMarketDeferredNoticeRecord)
                .where(DarkMarketDeferredNoticeRecord.listing_id.in_(listing_ids))
            )
            or 0
        )
    )
    row_counts = {
        "user_items": int(
            connection.scalar(select(func.count()).select_from(UserItemRecord)) or 0
        ),
        "equipment_ownerships": int(
            connection.scalar(select(func.count()).select_from(EquipmentOwnershipRecord))
            or 0
        ),
        "workstation_components": int(
            connection.scalar(select(func.count()).select_from(WorkstationComponentRecord))
            or 0
        ),
        "workstation_accessories": int(
            connection.scalar(select(func.count()).select_from(WorkstationAccessoryRecord))
            or 0
        ),
        "pending_promotions": pending_promotions,
        "reserved_item_uses": reserved_item_uses,
        "dark_market_current_bids": len(current_bid_rows),
        "dark_market_open_listings": len(listing_rows),
        "dark_market_deferred_notices": deferred_notices,
    }
    humans = [item for item in settlements if not item["is_bot"]]
    bots = [item for item in settlements if item["is_bot"]]
    summary = {
        "users": len(settlements),
        "human_users": len(humans),
        "bot_users": len(bots),
        "old_balance_total": sum(item["old_balance"] for item in settlements),
        "human_gross_value_total": sum(item["gross_value"] for item in humans),
        "bot_gross_value_excluded": sum(item["gross_value"] for item in bots),
        "new_balance_total": sum(item["new_balance"] for item in settlements),
        "balance_delta_total": sum(item["balance_delta"] for item in settlements),
        "asset_values": {
            key: sum(item["breakdown"]["values"][key] for item in settlements)
            for key in (
                "balance",
                "rank",
                "items",
                "workstation",
                "equipment",
                "dark_market",
            )
        },
        "rows_to_reset": row_counts,
    }
    rules_snapshot = {
        "season_code": SEASON_CODE,
        "formula": "human=max(0,gross*3//10); bot=0",
        "gross_components": [
            "balance",
            "current_rank.promotion_price",
            "positive_user_item_quantity*current_item.price",
            "workstation_highest_level_current_upgrade_costs",
            "owned_equipment_current_catalog_price",
            "current_dark_market_bid_on_open_listing",
        ],
        "carryover_numerator": CARRYOVER_NUMERATOR,
        "carryover_denominator": CARRYOVER_DENOMINATOR,
        "bot_platform_ids": sorted(BOT_PLATFORM_IDS),
        "new_rank": {"id": str(lv1.id), "name": lv1.name, "sort_order": 1},
        "pending_promotion_terminal_state": "expired",
        "dark_market_open_states": list(DARK_MARKET_ACTIVE_STATES),
        "dark_market_terminal_state": "force_delisted",
        "dark_market_refund_policy": "frozen value included in gross; no separate refund",
        "workstation_rules": {
            "version": workstation_version,
            "data": workstation_data,
            "effective_upgrade_costs": upgrade_costs,
        },
        "rank_catalog": rank_catalog,
        "item_catalog": item_catalog,
        "equipment_catalog": equipment_catalog,
        "preserved": [
            "departments",
            "honors",
            "tasks",
            "statistics",
            "shop_stock",
            "purchase_and_upgrade_history",
        ],
        "reset": [
            "users.balance",
            "users.rank_id",
            "user_items",
            "equipment_ownerships",
            "workstation_components",
            "workstation_accessories",
            "pending_promotion_requests",
            "open_dark_market_listings_and_current_bids",
        ],
    }
    plan = {
        "lv1_id": lv1.id,
        "settlements": settlements,
        "listing_ids": listing_ids,
        "rules_snapshot": rules_snapshot,
        "summary": summary,
    }
    plan["preview_digest"] = _plan_digest(plan)
    return plan


def _lock_reset_tables(connection) -> None:
    connection.execute(
        text(
            "LOCK TABLE company_seasons, company_season_settlements, users, "
            "balance_transactions, ranks, user_items, items, equipment_ownerships, "
            "equipment_items, workstation_rules, workstation_components, "
            "workstation_accessories, shop_item_uses, promotion_requests, dark_market_listings, "
            "dark_market_bids, dark_market_deferred_notices "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    )


def _apply_plan(
    connection,
    *,
    plan: dict,
    now: datetime,
    actor: str,
    seasons: Table,
    season_settlements: Table,
) -> dict:
    connection.execute(
        insert(seasons).values(
            code=SEASON_CODE,
            applied_at=now,
            applied_by=actor,
            carryover_numerator=CARRYOVER_NUMERATOR,
            carryover_denominator=CARRYOVER_DENOMINATOR,
            preview_digest=plan["preview_digest"],
            rules_snapshot=plan["rules_snapshot"],
            summary=plan["summary"],
        )
    )
    connection.execute(
        insert(season_settlements),
        [
            {
                "id": item["id"],
                "season_code": SEASON_CODE,
                "user_id": item["user_id"],
                "is_bot": item["is_bot"],
                "old_rank_id": item["old_rank_id"],
                "new_rank_id": item["new_rank_id"],
                "old_balance": item["old_balance"],
                "gross_value": item["gross_value"],
                "new_balance": item["new_balance"],
                "balance_delta": item["balance_delta"],
                "breakdown": item["breakdown"],
                "settled_at": now,
            }
            for item in plan["settlements"]
        ],
    )

    for item in plan["settlements"]:
        memo = (
            "S2赛季重置：自动账号清零"
            if item["is_bot"]
            else (
                f"S2赛季重置：总价值{item['gross_value']}，"
                f"按30%折算为{item['new_balance']}"
            )
        )
        connection.execute(
            insert(BalanceTransactionRecord).values(
                id=uuid4(),
                user_id=item["user_id"],
                amount=item["balance_delta"],
                source=BALANCE_SOURCE,
                memo=memo,
                occurred_at=now,
                dark_market_listing_id=None,
            )
        )
        connection.execute(
            update(UserRecord)
            .where(UserRecord.id == item["user_id"])
            .values(balance=item["new_balance"], rank_id=plan["lv1_id"])
        )

    applied_counts = {
        "user_items": int(connection.execute(delete(UserItemRecord)).rowcount or 0),
        "equipment_ownerships": int(
            connection.execute(delete(EquipmentOwnershipRecord)).rowcount or 0
        ),
        "workstation_components": int(
            connection.execute(delete(WorkstationComponentRecord)).rowcount or 0
        ),
        "workstation_accessories": int(
            connection.execute(delete(WorkstationAccessoryRecord)).rowcount or 0
        ),
    }
    applied_counts["pending_promotions"] = int(
        connection.execute(
            update(PromotionRequestRecord)
            .where(PromotionRequestRecord.state == "pending")
            .values(state="expired", decided_at=now)
        ).rowcount
        or 0
    )

    listing_ids = plan["listing_ids"]
    if listing_ids:
        applied_counts["dark_market_current_bids"] = int(
            connection.execute(
                update(DarkMarketBidRecord)
                .where(
                    DarkMarketBidRecord.listing_id.in_(listing_ids),
                    DarkMarketBidRecord.state == "current",
                )
                .values(state="refunded", refunded_at=now)
            ).rowcount
            or 0
        )
        receipt_states = ("awaiting_receipt", "complaint_pending")
        receipt_count = int(
            connection.execute(
                update(DarkMarketListingRecord)
                .where(
                    DarkMarketListingRecord.id.in_(listing_ids),
                    DarkMarketListingRecord.state.in_(receipt_states),
                )
                .values(
                    state="force_delisted",
                    receipt_resolved_at=now,
                    finished_at=now,
                )
            ).rowcount
            or 0
        )
        active_count = int(
            connection.execute(
                update(DarkMarketListingRecord)
                .where(
                    DarkMarketListingRecord.id.in_(listing_ids),
                    DarkMarketListingRecord.state == "active",
                )
                .values(state="force_delisted", finished_at=now)
            ).rowcount
            or 0
        )
        applied_counts["dark_market_open_listings"] = receipt_count + active_count
        applied_counts["dark_market_deferred_notices"] = int(
            connection.execute(
                delete(DarkMarketDeferredNoticeRecord).where(
                    DarkMarketDeferredNoticeRecord.listing_id.in_(listing_ids)
                )
            ).rowcount
            or 0
        )
    else:
        applied_counts.update(
            {
                "dark_market_current_bids": 0,
                "dark_market_open_listings": 0,
                "dark_market_deferred_notices": 0,
            }
        )

    expected = {
        item["user_id"]: (item["new_balance"], item["new_rank_id"])
        for item in plan["settlements"]
    }
    actual = {
        row.id: (int(row.balance), row.rank_id)
        for row in connection.execute(
            select(UserRecord.id, UserRecord.balance, UserRecord.rank_id)
        )
    }
    if actual != expected:
        raise RuntimeError("post-reset user balances or ranks do not match the plan")
    for model in (
        UserItemRecord,
        EquipmentOwnershipRecord,
        WorkstationComponentRecord,
        WorkstationAccessoryRecord,
    ):
        if connection.scalar(select(func.count()).select_from(model)):
            raise RuntimeError(f"post-reset table is not empty: {model.__tablename__}")
    if connection.scalar(
        select(func.count())
        .select_from(PromotionRequestRecord)
        .where(PromotionRequestRecord.state == "pending")
    ):
        raise RuntimeError("pending promotion requests remain after reset")
    if connection.scalar(
        select(func.count())
        .select_from(DarkMarketListingRecord)
        .where(DarkMarketListingRecord.state.in_(DARK_MARKET_ACTIVE_STATES))
    ):
        raise RuntimeError("open dark-market listings remain after reset")
    if connection.scalar(
        select(func.count())
        .select_from(DarkMarketBidRecord)
        .where(DarkMarketBidRecord.state == "current")
    ):
        raise RuntimeError("current dark-market bids remain after reset")
    settlement_count = int(
        connection.scalar(
            select(func.count())
            .select_from(season_settlements)
            .where(season_settlements.c.season_code == SEASON_CODE)
        )
        or 0
    )
    if settlement_count != len(plan["settlements"]):
        raise RuntimeError("company season settlement count does not match users")

    final_summary = {
        **plan["summary"],
        "rows_reset": applied_counts,
        "verified": True,
    }
    connection.execute(
        update(seasons)
        .where(seasons.c.code == SEASON_CODE)
        .values(summary=final_summary)
    )
    return final_summary


def run(
    *,
    apply: bool,
    actor: str,
    expect_digest: str | None = None,
    env_file: Path | None = None,
) -> dict:
    actor = actor.strip()
    if not actor or len(actor) > 128:
        raise ValueError("actor must contain 1 to 128 characters")
    if apply and not expect_digest:
        raise ValueError("--apply requires --expect-digest from the latest dry-run")
    if expect_digest is not None and (
        len(expect_digest) != 64
        or any(character not in "0123456789abcdef" for character in expect_digest)
    ):
        raise ValueError("expect_digest must be a lowercase SHA-256 digest")
    engine = create_engine(database_url(env_file), pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("S2 reset only supports PostgreSQL")
        with engine.connect() as base_connection:
            connection = base_connection.execution_options(
                isolation_level="SERIALIZABLE"
            )
            with connection.begin():
                required_tables = {
                    "company_seasons",
                    "company_season_settlements",
                }
                missing_tables = sorted(
                    table
                    for table in required_tables
                    if not inspect(connection).has_table(table)
                )
                if missing_tables:
                    raise RuntimeError(
                        "run Alembic migrations first; missing: "
                        + ", ".join(missing_tables)
                    )
                metadata = MetaData()
                seasons = Table("company_seasons", metadata, autoload_with=connection)
                season_settlements = Table(
                    "company_season_settlements", metadata, autoload_with=connection
                )
                connection.execute(
                    text(
                        "SELECT pg_advisory_xact_lock(:namespace, :lock_key)"
                    ),
                    {
                        "namespace": ADVISORY_LOCK_NAMESPACE,
                        "lock_key": ADVISORY_LOCK_KEY,
                    },
                )
                if apply:
                    _lock_reset_tables(connection)
                existing = connection.execute(
                    select(seasons.c.applied_at, seasons.c.applied_by).where(
                        seasons.c.code == SEASON_CODE
                    )
                ).one_or_none()
                if existing is not None:
                    raise RuntimeError(
                        f"{SEASON_CODE} was already applied at {existing.applied_at} "
                        f"by {existing.applied_by}"
                    )
                now = datetime.now(timezone.utc)
                plan = _load_plan(connection, now)
                if apply and plan["preview_digest"] != expect_digest:
                    raise RuntimeError(
                        "preview digest mismatch; run a new dry-run and review it before apply"
                    )
                if not apply:
                    return {
                        "mode": "dry-run",
                        "season_code": SEASON_CODE,
                        "preview_digest": plan["preview_digest"],
                        "summary": plan["summary"],
                    }
                final_summary = _apply_plan(
                    connection,
                    plan=plan,
                    now=now,
                    actor=actor,
                    seasons=seasons,
                    season_settlements=season_settlements,
                )
                return {
                    "mode": "applied",
                    "season_code": SEASON_CODE,
                    "applied_at": now.isoformat(),
                    "applied_by": actor,
                    "preview_digest": plan["preview_digest"],
                    "summary": final_summary,
                }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply S2. Without this flag, only print the dry-run aggregate and digest.",
    )
    parser.add_argument(
        "--expect-digest",
        help="Required with --apply; copy preview_digest from the reviewed dry-run.",
    )
    parser.add_argument(
        "--actor",
        default=getpass.getuser(),
        help="Operator recorded in the immutable season audit row.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Private server env file; DZMM_DATABASE_URL takes precedence.",
    )
    args = parser.parse_args()
    try:
        result = run(
            apply=args.apply,
            actor=args.actor,
            expect_digest=args.expect_digest,
            env_file=args.env_file,
        )
    except (RuntimeError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
