import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_reset_script():
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        return _load_module("reset_company_season", scripts / "reset_company_season.py")
    finally:
        sys.path.remove(str(scripts))


def _digest_plan(*, settlement_id=None, gross_value=100):
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    lv1_id = UUID("22222222-2222-2222-2222-222222222222")
    listing_id = UUID("33333333-3333-3333-3333-333333333333")
    return {
        "rules_snapshot": {"formula": "human=max(0,gross*3//10); bot=0"},
        "summary": {"users": 1, "human_gross_value_total": gross_value},
        "listing_ids": [listing_id],
        "settlements": [
            {
                "id": settlement_id or uuid4(),
                "user_id": user_id,
                "is_bot": False,
                "old_rank_id": lv1_id,
                "new_rank_id": lv1_id,
                "old_balance": gross_value,
                "gross_value": gross_value,
                "new_balance": gross_value * 3 // 10,
                "balance_delta": gross_value * 3 // 10 - gross_value,
                "breakdown": {"values": {"balance": gross_value}},
            }
        ],
    }


def _seed_reset_database(engine, script, *, listing_state="active"):
    from dzmm_bot.core.schema import (
        Base,
        DarkMarketBidRecord,
        DarkMarketListingRecord,
        EquipmentItemRecord,
        EquipmentOwnershipRecord,
        ItemRecord,
        PromotionRequestRecord,
        RankRecord,
        UserItemRecord,
        UserRecord,
        WorkstationAccessoryRecord,
        WorkstationComponentRecord,
        WorkstationRulesRecord,
    )

    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    lv1_id = UUID("10000000-0000-0000-0000-000000000001")
    lv2_id = UUID("10000000-0000-0000-0000-000000000002")
    human_id = UUID("20000000-0000-0000-0000-000000000001")
    bot_id = UUID("20000000-0000-0000-0000-000000000002")
    item_id = UUID("30000000-0000-0000-0000-000000000001")
    equipment_id = UUID("40000000-0000-0000-0000-000000000001")
    listing_id = UUID("50000000-0000-0000-0000-000000000001")

    Base.metadata.create_all(engine)
    migration = _load_module(
        "company_seasons_apply_migration",
        ROOT / "migrations" / "versions" / "20261111_112_company_seasons.py",
    )
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.execute(
            sa.insert(RankRecord),
            [
                {
                    "id": lv1_id,
                    "sort_order": 1,
                    "name": "LV1",
                    "level_label": "LV1",
                    "promotion_price": 100,
                    "checkin_reward": 1,
                    "vote_weight": 1,
                    "multiplayer_game_limit": 1,
                    "has_group_management": False,
                    "is_board": False,
                    "enabled": True,
                },
                {
                    "id": lv2_id,
                    "sort_order": 2,
                    "name": "LV2",
                    "level_label": "LV2",
                    "promotion_price": 11,
                    "checkin_reward": 1,
                    "vote_weight": 1,
                    "multiplayer_game_limit": 1,
                    "has_group_management": False,
                    "is_board": False,
                    "enabled": True,
                },
            ],
        )
        connection.execute(
            sa.insert(UserRecord),
            [
                {
                    "id": human_id,
                    "platform_id": "human-platform-id",
                    "display_name": "human",
                    "gender": "unknown",
                    "employee_number": 1,
                    "balance": 1,
                    "profile_text": "",
                    "profile_version": 0,
                    "rank_id": lv2_id,
                    "joined_at": now,
                },
                {
                    "id": bot_id,
                    "platform_id": sorted(script.BOT_PLATFORM_IDS)[0],
                    "display_name": "bot",
                    "gender": "unknown",
                    "employee_number": 2,
                    "balance": 99,
                    "profile_text": "",
                    "profile_version": 0,
                    "rank_id": lv2_id,
                    "joined_at": now,
                },
            ],
        )
        connection.execute(
            sa.insert(ItemRecord).values(
                id=item_id,
                public_number=1,
                name="item",
                description="test",
                price=3,
                stock=10,
                unlimited_stock=False,
                configuration_version=1,
                enabled=True,
                created_at=now,
            )
        )
        connection.execute(
            sa.insert(UserItemRecord).values(
                id=uuid4(),
                user_id=human_id,
                item_id=item_id,
                quantity=2,
                created_at=now,
            )
        )
        connection.execute(
            sa.insert(WorkstationRulesRecord).values(
                id=1,
                version=3,
                data={"upgrade_costs": [2, 3, 5, 7, 11, 13, 17, 19, 23]},
            )
        )
        connection.execute(
            sa.insert(WorkstationComponentRecord).values(
                user_id=human_id,
                category_number=1,
                highest_level=3,
                active_level=3,
                equipped=True,
            )
        )
        connection.execute(
            sa.insert(WorkstationAccessoryRecord).values(
                user_id=human_id,
                accessory_number=1,
                equipped=True,
            )
        )
        connection.execute(
            sa.insert(EquipmentItemRecord).values(
                id=equipment_id,
                public_number=1,
                asset_key="equipment",
                name="equipment",
                price=4,
                daily_income=0,
                enabled=True,
            )
        )
        connection.execute(
            sa.insert(EquipmentOwnershipRecord).values(
                id=uuid4(),
                user_id=human_id,
                item_id=equipment_id,
                equipped=True,
                purchased_at=now,
            )
        )
        connection.execute(
            sa.insert(PromotionRequestRecord).values(
                id=uuid4(),
                applicant_id=human_id,
                source_rank_id=lv1_id,
                target_rank_id=lv2_id,
                price=11,
                state="pending",
                requested_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        connection.execute(
            sa.insert(DarkMarketListingRecord).values(
                id=listing_id,
                public_number=1,
                seller_user_id=bot_id,
                announcement_group_id=uuid4(),
                name="listing",
                purpose="test",
                details="test",
                gender="private",
                starting_price=1,
                duration_hours_snapshot=1,
                fee_percent_snapshot=0,
                state=listing_state,
                ends_at=now + timedelta(hours=1),
                created_at=now,
            )
        )
        connection.execute(
            sa.insert(DarkMarketBidRecord).values(
                id=uuid4(),
                listing_id=listing_id,
                bidder_user_id=human_id,
                inbound_message_id=uuid4(),
                amount=7,
                state="current",
                created_at=now,
            )
        )

    return {
        "now": now,
        "lv1_id": lv1_id,
        "human_id": human_id,
        "bot_id": bot_id,
        "listing_id": listing_id,
    }


def test_reset_math_and_preview_digest_are_deterministic():
    script = _load_reset_script()

    assert script._workstation_cost(1, [20, 40, 70, 120, 200, 300, 400, 600, 800]) == 0
    assert script._workstation_cost(4, [20, 40, 70, 120, 200, 300, 400, 600, 800]) == 130

    first = _digest_plan()
    same_inputs_new_receipt = _digest_plan()
    changed_value = _digest_plan(gross_value=101)
    assert script._plan_digest(first) == script._plan_digest(same_inputs_new_receipt)
    assert script._plan_digest(first) != script._plan_digest(changed_value)


def test_load_plan_values_assets_and_floors_each_user(tmp_path):
    script = _load_reset_script()
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "plan.db"))
    ids = _seed_reset_database(engine, script)

    with engine.connect() as connection:
        plan = script._load_plan(connection, ids["now"])

    settlements = {
        item["user_id"]: item for item in plan["settlements"]
    }
    human = settlements[ids["human_id"]]
    bot = settlements[ids["bot_id"]]
    assert human["breakdown"]["values"] == {
        "balance": 1,
        "rank": 11,
        "items": 6,
        "workstation": 5,
        "equipment": 4,
        "dark_market": 7,
    }
    assert human["gross_value"] == 34
    assert human["new_balance"] == 10
    assert bot["gross_value"] == 110
    assert bot["new_balance"] == 0
    assert plan["summary"]["new_balance_total"] == 10
    assert len(plan["preview_digest"]) == 64


@pytest.mark.parametrize(
    "listing_state", ["active", "awaiting_receipt", "complaint_pending"]
)
def test_apply_plan_resets_current_state_and_writes_audit(tmp_path, listing_state):
    script = _load_reset_script()
    from dzmm_bot.core.schema import (
        BalanceTransactionRecord,
        DarkMarketBidRecord,
        DarkMarketListingRecord,
        EquipmentOwnershipRecord,
        PromotionRequestRecord,
        UserItemRecord,
        UserRecord,
        WorkstationAccessoryRecord,
        WorkstationComponentRecord,
    )

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "apply.db"))
    ids = _seed_reset_database(engine, script, listing_state=listing_state)
    metadata = sa.MetaData()
    with engine.begin() as connection:
        seasons = sa.Table("company_seasons", metadata, autoload_with=connection)
        settlements = sa.Table(
            "company_season_settlements",
            metadata,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_id", sa.Uuid()),
            sa.Column("old_rank_id", sa.Uuid()),
            sa.Column("new_rank_id", sa.Uuid()),
            autoload_with=connection,
            extend_existing=True,
        )
        plan = script._load_plan(connection, ids["now"])
        summary = script._apply_plan(
            connection,
            plan=plan,
            now=ids["now"],
            actor="pytest",
            seasons=seasons,
            season_settlements=settlements,
        )

        users = {
            row.id: (row.balance, row.rank_id)
            for row in connection.execute(
                sa.select(UserRecord.id, UserRecord.balance, UserRecord.rank_id)
            )
        }
        assert users[ids["human_id"]] == (10, ids["lv1_id"])
        assert users[ids["bot_id"]] == (0, ids["lv1_id"])
        for model in (
            UserItemRecord,
            EquipmentOwnershipRecord,
            WorkstationComponentRecord,
            WorkstationAccessoryRecord,
        ):
            assert connection.scalar(sa.select(sa.func.count()).select_from(model)) == 0
        assert connection.scalar(
            sa.select(PromotionRequestRecord.state)
        ) == "expired"
        assert connection.scalar(
            sa.select(DarkMarketListingRecord.state)
        ) == "force_delisted"
        assert connection.scalar(sa.select(DarkMarketBidRecord.state)) == "refunded"
        ledger = {
            row.user_id: row.amount
            for row in connection.execute(
                sa.select(
                    BalanceTransactionRecord.user_id,
                    BalanceTransactionRecord.amount,
                ).where(BalanceTransactionRecord.source == script.BALANCE_SOURCE)
            )
        }
        assert ledger == {ids["human_id"]: 9, ids["bot_id"]: -99}
        assert sum(ledger.values()) == plan["summary"]["balance_delta_total"]
        season = connection.execute(sa.select(seasons)).mappings().one()
        assert season["code"] == "S2"
        assert season["preview_digest"] == plan["preview_digest"]
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(settlements)
        ) == 2
        assert summary["verified"] is True


def test_load_plan_rejects_reserved_shop_items(tmp_path):
    script = _load_reset_script()
    from dzmm_bot.core.schema import ShopItemUseRecord

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "reserved.db"))
    ids = _seed_reset_database(engine, script)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(ShopItemUseRecord).values(
                id=uuid4(),
                inbound_message_id=uuid4(),
                user_id=ids["human_id"],
                item_id=UUID("30000000-0000-0000-0000-000000000001"),
                group_chat_id=uuid4(),
                state="reserved",
                created_at=ids["now"],
            )
        )
        with pytest.raises(RuntimeError, match="reserved shop items"):
            script._load_plan(connection, ids["now"])


def test_company_season_migration_includes_preview_digest(tmp_path):
    migration = _load_module(
        "company_seasons_migration",
        ROOT / "migrations" / "versions" / "20261111_112_company_seasons.py",
    )
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "season.db"))
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("ranks", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    metadata.create_all(engine)

    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            columns = {
                column["name"]: column for column in sa.inspect(connection).get_columns(
                    "company_seasons"
                )
            }
            assert columns["preview_digest"]["nullable"] is False
            migration.downgrade()

    assert "company_seasons" not in sa.inspect(engine).get_table_names()
