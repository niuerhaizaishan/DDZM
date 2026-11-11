"""Prices copied from 工位系统.xlsx and used by both shop and growth actions."""

from dzmm_bot.core.workstation_catalog import (
    ENVIRONMENT_INCOME,
    component_daily_income,
    TOOL_INCOME,
    UPGRADE_COSTS,
    environment_daily_income,
    environment_upgrade_cost,
    upgrade_cost,
)
from dzmm_bot.core.workstation_growth import batch_growth_plan


def _components(stage):
    return [
        {
            "number": number,
            "category": str(number),
            "highest_level": stage * 2 - 1 if number <= 5 else stage * 2,
            "active_level": stage * 2 - 1 if number <= 5 else stage * 2,
            "equipped": True,
        }
        for number in range(1, 10)
    ]


def test_workbook_price_and_income_tables_are_canonical():
    assert UPGRADE_COSTS == (20, 40, 70, 120, 200, 300, 400, 600, 800)
    assert ENVIRONMENT_INCOME == (0, 0, 2, 2, 5, 5, 10, 10, 20, 20)
    assert TOOL_INCOME == (0, 2, 5, 10, 15, 20, 25, 30, 35, 40)
    assert [upgrade_cost(level) for level in range(1, 10)] == list(UPGRADE_COSTS)


def test_environment_upgrade_sums_all_five_layout_items_and_four_devices():
    # /升级工位 moves the five environment items to the next base tier and
    # the four devices to that same environment's base tier.
    expected_environment = (300, 950, 2500, 5000)
    expected_devices = (160, 480, 1200, 2400)
    expected_total = (460, 1430, 3700, 7400)
    for stage, (environment_price, device_price, total_price) in enumerate(
        zip(expected_environment, expected_devices, expected_total), start=1
    ):
        components = _components(stage)
        plan = batch_growth_plan(components, "advance")
        assert plan["status"] == "available"
        assert plan["price"] == total_price
        environment_total = sum(
            upgrade_cost(c["highest_level"], plan["targets"][c["number"]])
            for c in components
            if c["number"] <= 5
        )
        device_total = sum(
            upgrade_cost(c["highest_level"], plan["targets"][c["number"]])
            for c in components
            if c["number"] >= 6
        )
        assert environment_total == environment_price
        assert device_total == device_price


def test_environment_upgrade_payback_days_match_price_and_income_tables():
    expected = ((460, 14, 460 / 14), (1430, 23, 1430 / 23),
                (3700, 25, 3700 / 25), (7400, 30, 7400 / 30))
    for stage, (price, income_delta, payback) in enumerate(expected, start=1):
        components = _components(stage)
        plan = batch_growth_plan(components, "advance")
        before = sum(
            component_daily_income(c["number"], c["active_level"])
            for c in components
        )
        after = sum(
            component_daily_income(c["number"], plan["targets"][c["number"]])
            for c in components
        )
        assert plan["price"] == price
        assert after - before == income_delta
        assert round(plan["price"] / (after - before), 1) == round(payback, 1)


def test_one_or_two_device_upgrades_scale_cost_and_income_together():
    expected = ((20, 2, 10.0), (70, 5, 14.0), (200, 5, 40.0),
                (400, 5, 80.0), (800, 5, 160.0))
    for environment, (price, income_delta, payback) in enumerate(expected, start=1):
        from_level = environment * 2 - 1
        single_price = upgrade_cost(from_level)
        single_delta = TOOL_INCOME[from_level] - TOOL_INCOME[from_level - 1]
        assert (single_price, single_delta, single_price / single_delta) == (price, income_delta, payback)
        assert (2 * single_price, 2 * single_delta,
                (2 * single_price) / (2 * single_delta)) == (2 * price, 2 * income_delta, payback)


def test_environment_table_has_five_bundled_levels():
    assert [environment_daily_income(level) for level in range(1, 6)] == [0, 2, 5, 10, 20]
    assert [environment_upgrade_cost(level) for level in range(1, 5)] == [460, 1430, 3700, 7400]
