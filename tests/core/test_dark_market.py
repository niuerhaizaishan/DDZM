import pytest

from dzmm_bot.core.dark_market import (
    DarkMarketListingView,
    calculate_fee,
    minimum_next_bid,
    normalize_listing_field,
    render_listing_detail,
    render_listing_summary,
)


@pytest.mark.parametrize(
    ("amount", "percent", "fee"),
    [(1, 5, 1), (20, 5, 1), (21, 5, 2), (99999, 100, 99999)],
)
def test_calculate_fee_rounds_up_with_minimum_one(amount, percent, fee) -> None:
    assert calculate_fee(amount, percent) == fee


@pytest.mark.parametrize("percent", [0, 101])
def test_calculate_fee_rejects_invalid_percent(percent) -> None:
    with pytest.raises(ValueError, match="invalid fee percent"):
        calculate_fee(10, percent)


def test_minimum_next_bid_uses_starting_price_then_one_coin_increment() -> None:
    assert minimum_next_bid(15, None) == 15
    assert minimum_next_bid(15, 22) == 23


@pytest.mark.parametrize(
    ("step", "content", "expected"),
    [
        ("name", " 旧钥匙 ", "旧钥匙"),
        ("purpose", " 打开未知房门 ", "打开未知房门"),
        ("details", " 来历不明 ", "来历不明"),
        ("gender", "男", "male"),
        ("gender", "女", "female"),
        ("gender", "保密", "private"),
        ("starting_price", " 99 ", 99),
    ],
)
def test_normalize_listing_field_accepts_valid_player_input(
    step, content, expected
) -> None:
    assert normalize_listing_field(step, content) == expected


@pytest.mark.parametrize(
    ("step", "content"),
    [
        ("name", " "),
        ("name", "名" * 31),
        ("purpose", "用" * 101),
        ("details", "详" * 501),
        ("gender", "未知"),
        ("starting_price", "0"),
        ("starting_price", "100000"),
        ("starting_price", "1.5"),
        ("preview", "确认"),
    ],
)
def test_normalize_listing_field_rejects_invalid_player_input(step, content) -> None:
    with pytest.raises(ValueError):
        normalize_listing_field(step, content)


def test_player_rendering_contains_only_public_fields_and_hides_deadline() -> None:
    view = DarkMarketListingView(
        public_number=12,
        name="旧钥匙",
        purpose="开门",
        details="未知来历",
        gender="private",
        starting_price=10,
        current_price=18,
        state="active",
    )

    summary = render_listing_summary(view)
    detail = render_listing_detail(view)

    assert summary == "#12 旧钥匙｜用途：开门｜性别：保密｜起拍 10｜当前 18｜竞价中"
    assert "详细信息：未知来历" in detail
    assert "截止" not in detail
    assert "剩余" not in detail
    assert "卖家" not in detail
    assert "买家" not in detail
