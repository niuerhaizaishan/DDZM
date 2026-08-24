from datetime import UTC, datetime, timedelta
from random import Random
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    BalanceTransactionRecord,
    Base,
    DarkMarketBidRecord,
    DarkMarketDisclosureRecord,
    DarkMarketListingRecord,
    OutboundRecord,
    PRIMARY_GROUP_CHAT_ID,
    UserRecord,
)
from dzmm_bot.runtime.contracts import InboundMessage


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


@pytest.fixture
def repository() -> CoreRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return CoreRepository(sessionmaker(engine, expire_on_commit=False), number_bomb_random=Random(1))


def _configure_market(repository: CoreRepository, now: datetime) -> None:
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=dark-market-room", now
    )
    settings = repository.get_dark_market_settings()
    repository.set_dark_market_settings(
        enabled=True,
        announcement_group_id=PRIMARY_GROUP_CHAT_ID,
        duration_hours=3,
        fee_percent=5,
        rank_limits={limit.rank_id: limit.daily_limit for limit in settings.rank_limits},
        expected_version=settings.version,
    )


def _complete_draft(
    repository: CoreRepository, platform_id: str, now: datetime
) -> None:
    assert repository.start_dark_market_draft(platform_id, now).status == "started"
    assert repository.advance_dark_market_draft(platform_id, "旧钥匙", now).step == "purpose"
    assert repository.advance_dark_market_draft(platform_id, "打开未知房门", now).step == "details"
    assert repository.advance_dark_market_draft(platform_id, "来历不明", now).step == "gender"
    assert repository.advance_dark_market_draft(platform_id, "保密", now).step == "starting_price"
    preview = repository.advance_dark_market_draft(platform_id, "10", now)
    assert preview.status == "preview"
    assert preview.step == "preview"
    assert "旧钥匙" in preview.preview_text


def _inbound_id(
    repository: CoreRepository,
    platform_id: str,
    content: str,
    now: datetime,
):
    inbound, inserted = repository.accept_inbound(
        InboundMessage(
            f"{platform_id}-{content}-{uuid4()}",
            platform_id,
            content,
            now,
            source_type="direct",
            chatroom_id=f"direct-{platform_id}",
        )
    )
    assert inserted
    return inbound.id


def _active_listing(repository: CoreRepository, now: datetime):
    repository.create_user("seller", "真实卖家", now, 100)
    repository.create_user("buyer-a", "买家甲", now, 100)
    repository.create_user("buyer-b", "买家乙", now, 100)
    repository.upsert_direct_chats(
        [
            ("seller", "direct-seller"),
            ("buyer-a", "direct-buyer-a"),
            ("buyer-b", "direct-buyer-b"),
        ],
        now,
    )
    _configure_market(repository, now)
    _complete_draft(repository, "seller", now)
    result = repository.confirm_dark_market_listing("seller", uuid4(), now)
    assert result.listing is not None
    return result.listing


def _balance(repository: CoreRepository, platform_id: str) -> int:
    profile = repository.get_user_profile(platform_id)
    assert profile is not None
    return profile.user.balance


def test_dark_market_settings_seed_all_rank_limits(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)

    settings = repository.get_dark_market_settings()

    assert settings.enabled is True
    assert settings.announcement_group_id is None
    assert settings.duration_hours == 3
    assert settings.fee_percent == 5
    assert [limit.daily_limit for limit in settings.rank_limits] == [
        1, 1, 2, 2, 3, 3, 4, 4, 5, 5, -1
    ]


def test_dark_market_settings_require_an_enabled_listening_group(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    settings = repository.get_dark_market_settings()

    with pytest.raises(ValueError, match="暗网群聊不可用"):
        repository.set_dark_market_settings(
            enabled=True,
            announcement_group_id=uuid4(),
            duration_hours=3,
            fee_percent=5,
            rank_limits={limit.rank_id: limit.daily_limit for limit in settings.rank_limits},
            expected_version=settings.version,
        )


def test_dark_market_draft_resumes_and_rejects_invalid_field(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    _configure_market(repository, now)

    started = repository.start_dark_market_draft("seller", now)
    invalid = repository.advance_dark_market_draft("seller", "名" * 31, now)
    resumed = repository.start_dark_market_draft("seller", now + timedelta(minutes=1))

    assert started.status == "started"
    assert invalid.status == "invalid"
    assert invalid.step == "name"
    assert resumed.status == "resumed"
    assert resumed.step == "name"


def test_dark_market_draft_can_be_cancelled_and_expires(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    _configure_market(repository, now)
    repository.start_dark_market_draft("seller", now)

    assert repository.cancel_dark_market_draft("seller", now).status == "cancelled"
    assert repository.cancel_dark_market_draft("seller", now).status == "no_draft"

    repository.start_dark_market_draft("seller", now)
    restarted = repository.start_dark_market_draft(
        "seller", now + timedelta(minutes=31)
    )
    assert restarted.status == "started"
    assert restarted.step == "name"


def test_confirm_listing_consumes_quota_and_enqueues_anonymous_announcement(
    repository, now
) -> None:
    repository.create_user("seller", "真实卖家", now, 100)
    _configure_market(repository, now)
    _complete_draft(repository, "seller", now)

    result = repository.confirm_dark_market_listing("seller", uuid4(), now)

    assert result.status == "listed"
    assert result.listing is not None
    assert result.listing.public_number == 1
    assert result.listing.ends_at == now + timedelta(hours=3)
    assert result.listing.fee_percent_snapshot == 5
    outbound = repository.claim_outbound(
        "worker", now, 30, required_delivery_key="dark-market-room"
    )
    assert outbound is not None
    assert "暗网新商品 #1" in outbound.text
    assert "旧钥匙" in outbound.text
    assert "真实卖家" not in outbound.text
    assert "截止" not in outbound.text

    _complete_draft(repository, "seller", now)
    limited = repository.confirm_dark_market_listing("seller", uuid4(), now)
    assert limited.status == "daily_limit"


def test_listing_numbers_are_never_reused(repository, now) -> None:
    repository.create_user("seller-a", "卖家甲", now, 100)
    repository.create_user("seller-b", "卖家乙", now, 100)
    _configure_market(repository, now)
    _complete_draft(repository, "seller-a", now)
    _complete_draft(repository, "seller-b", now)

    first = repository.confirm_dark_market_listing("seller-a", uuid4(), now)
    second = repository.confirm_dark_market_listing("seller-b", uuid4(), now)

    assert first.listing is not None
    assert second.listing is not None
    assert (first.listing.public_number, second.listing.public_number) == (1, 2)


def test_outbid_refund_and_new_freeze_are_atomic(repository, now) -> None:
    listing = _active_listing(repository, now)

    first = repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )
    second = repository.place_dark_market_bid(
        "buyer-b", listing.public_number, 25,
        _inbound_id(repository, "buyer-b", "/报价 1 25", now), now,
    )

    assert first.status == "accepted"
    assert second.status == "accepted"
    assert _balance(repository, "buyer-a") == 100
    assert _balance(repository, "buyer-b") == 75
    with repository._session() as session:
        bids = list(
            session.scalars(
                select(DarkMarketBidRecord).order_by(DarkMarketBidRecord.created_at)
            )
        )
        sources = list(
            session.scalars(
                select(BalanceTransactionRecord.source)
                .where(BalanceTransactionRecord.source.like("dark_market_%"))
                .order_by(BalanceTransactionRecord.occurred_at, BalanceTransactionRecord.id)
            )
        )
    assert [bid.state for bid in bids] == ["refunded", "current"]
    assert set(sources) == {"dark_market_bid_hold", "dark_market_bid_refund"}


def test_same_bidder_only_freezes_raise_difference(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )

    raised = repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 27,
        _inbound_id(repository, "buyer-a", "/报价 1 27", now), now,
    )

    assert raised.status == "accepted"
    assert raised.frozen_amount == 27
    assert _balance(repository, "buyer-a") == 73


def test_bid_rejects_low_amount_insufficient_balance_and_deadline(repository, now) -> None:
    listing = _active_listing(repository, now)

    too_low = repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 9,
        _inbound_id(repository, "buyer-a", "/报价 1 9", now), now,
    )
    too_expensive = repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 101,
        _inbound_id(repository, "buyer-a", "/报价 1 101", now), now,
    )
    expired = repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 10,
        _inbound_id(repository, "buyer-a", "/报价 1 10", listing.ends_at),
        listing.ends_at,
    )

    assert too_low.status == "too_low"
    assert too_expensive.status == "insufficient_balance"
    assert expired.status == "ended"
    assert _balance(repository, "buyer-a") == 100


def test_sale_is_conservative_and_fee_rounds_up(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )

    repository.run_dark_market_jobs(listing.ends_at)

    assert _balance(repository, "buyer-a") == 79
    assert _balance(repository, "seller") == 119
    with repository._session() as session:
        stored = session.scalar(
            select(DarkMarketListingRecord).where(
                DarkMarketListingRecord.id == listing.id
            )
        )
        ledger = session.execute(
            select(BalanceTransactionRecord.amount, BalanceTransactionRecord.source)
            .where(BalanceTransactionRecord.source.like("dark_market_sale_%"))
        ).all()
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert stored is not None
    assert (stored.state, stored.final_amount, stored.fee_amount) == ("sold", 21, 2)
    assert set(ledger) == {(21, "dark_market_sale_income"), (-2, "dark_market_sale_fee")}
    assert disclosure is not None
    assert disclosure.deadline == listing.ends_at + timedelta(minutes=10)


def test_seller_self_sale_still_pays_fee(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "seller", listing.public_number, 20,
        _inbound_id(repository, "seller", "/报价 1 20", now), now,
    )

    repository.run_dark_market_jobs(listing.ends_at)

    assert _balance(repository, "seller") == 99
    with repository._session() as session:
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert disclosure is not None
    assert disclosure.seller_user_id == disclosure.buyer_user_id


def test_force_delist_refunds_current_bid_without_fee(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )

    result = repository.force_delist_dark_market_listing(listing.id, now)
    repeated = repository.force_delist_dark_market_listing(listing.id, now)

    assert result.status == "force_delisted"
    assert repeated.status == "already_ended"
    assert _balance(repository, "buyer-a") == 100
    assert _balance(repository, "seller") == 100


def test_disclosure_requires_both_parties_and_self_sale_only_one(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)

    seller = repository.decide_dark_market_disclosure(
        "seller", listing.public_number, True,
        _inbound_id(repository, "seller", "/公开 1", listing.ends_at), listing.ends_at,
    )
    buyer = repository.decide_dark_market_disclosure(
        "buyer-a", listing.public_number, True,
        _inbound_id(repository, "buyer-a", "/公开 1", listing.ends_at), listing.ends_at,
    )

    assert seller.status == "waiting_other"
    assert buyer.status == "revealed"
    with repository._session() as session:
        public_messages = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "group",
                    OutboundRecord.text.like("%真实卖家%"),
                )
            )
        )
    assert any("买家甲" in message for message in public_messages)


def test_disclosure_timeout_keeps_both_identities_anonymous(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)

    repository.run_dark_market_jobs(listing.ends_at + timedelta(minutes=10))

    with repository._session() as session:
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert disclosure is not None
    assert disclosure.state == "anonymous"


def test_daily_jobs_run_global_dark_market_settlement(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )

    repository.run_daily_jobs(listing.ends_at)

    with repository._session() as session:
        stored = session.get(DarkMarketListingRecord, listing.id)
    assert stored is not None
    assert stored.state == "sold"


def test_one_failed_settlement_does_not_block_other_due_listings(
    repository, now, monkeypatch
) -> None:
    first = _active_listing(repository, now)
    repository.create_user("seller-b", "卖家乙", now, 100)
    repository.upsert_direct_chats([("seller-b", "direct-seller-b")], now)
    _complete_draft(repository, "seller-b", now)
    second_result = repository.confirm_dark_market_listing("seller-b", uuid4(), now)
    assert second_result.listing is not None
    second = second_result.listing
    original = repository._settle_dark_market_listing

    def settle(session, listing, settled_at):
        if listing.id == first.id:
            raise RuntimeError("broken first listing")
        original(session, listing, settled_at)

    monkeypatch.setattr(repository, "_settle_dark_market_listing", settle)

    repository.run_dark_market_jobs(first.ends_at)

    with repository._session() as session:
        stored_first = session.get(DarkMarketListingRecord, first.id)
        stored_second = session.get(DarkMarketListingRecord, second.id)
    assert stored_first is not None
    assert stored_second is not None
    assert stored_first.state == "active"
    assert stored_second.state == "unsold"
