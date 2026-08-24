from dataclasses import dataclass


_GENDER_LABELS = {
    "male": "男",
    "female": "女",
    "private": "保密",
}
_GENDER_VALUES = {label: value for value, label in _GENDER_LABELS.items()}
_TEXT_LIMITS = {
    "name": 30,
    "purpose": 100,
    "details": 500,
}


@dataclass(frozen=True)
class DarkMarketListingView:
    public_number: int
    name: str
    purpose: str
    details: str
    gender: str
    starting_price: int
    current_price: int | None
    state: str


def normalize_listing_field(step: str, content: str) -> str | int:
    value = content.strip()
    if step in _TEXT_LIMITS:
        if not value or len(value) > _TEXT_LIMITS[step]:
            raise ValueError(f"invalid {step}")
        return value
    if step == "gender":
        try:
            return _GENDER_VALUES[value]
        except KeyError as exc:
            raise ValueError("invalid gender") from exc
    if step == "starting_price":
        try:
            amount = int(value)
        except ValueError as exc:
            raise ValueError("invalid starting price") from exc
        if str(amount) != value or not 1 <= amount <= 99999:
            raise ValueError("invalid starting price")
        return amount
    raise ValueError("invalid listing step")


def minimum_next_bid(starting_price: int, current_price: int | None) -> int:
    return starting_price if current_price is None else current_price + 1


def calculate_fee(amount: int, fee_percent: int) -> int:
    if not 1 <= fee_percent <= 100:
        raise ValueError("invalid fee percent")
    return max(1, (amount * fee_percent + 99) // 100)


def render_listing_summary(listing: DarkMarketListingView) -> str:
    current = (
        "暂无报价"
        if listing.current_price is None
        else f"当前 {listing.current_price}"
    )
    state = "竞价中" if listing.state == "active" else listing.state
    return (
        f"#{listing.public_number} {listing.name}｜用途：{listing.purpose}｜"
        f"性别：{_GENDER_LABELS[listing.gender]}｜起拍 {listing.starting_price}｜"
        f"{current}｜{state}"
    )


def render_listing_detail(listing: DarkMarketListingView) -> str:
    return f"{render_listing_summary(listing)}\n详细信息：{listing.details}"
