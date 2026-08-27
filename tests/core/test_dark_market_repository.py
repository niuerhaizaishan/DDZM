from datetime import UTC, datetime, timedelta
from random import Random
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
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
        disclosure_duration_value=settings.disclosure_duration_value,
        disclosure_duration_unit=settings.disclosure_duration_unit,
        rank_limits={limit.rank_id: limit.daily_limit for limit in settings.rank_limits},
        expected_version=settings.version,
        now=now,
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


def _confirm_listing(repository: CoreRepository, listing, now: datetime):
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    confirmed_at = listing.ends_at + timedelta(hours=1)
    result = repository.resolve_dark_market_receipt(
        "buyer-a",
        listing.public_number,
        "confirm",
        _inbound_id(repository, "buyer-a", "/确认收货 1", confirmed_at),
        confirmed_at,
    )
    assert result.status == "confirmed"
    return confirmed_at


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
    assert settings.disclosure_duration_value == 10
    assert settings.disclosure_duration_unit == "minute"
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
            disclosure_duration_value=settings.disclosure_duration_value,
            disclosure_duration_unit=settings.disclosure_duration_unit,
            rank_limits={limit.rank_id: limit.daily_limit for limit in settings.rank_limits},
            expected_version=settings.version,
            now=now,
        )


def test_dark_market_draft_resumes_and_rejects_invalid_field(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    repository.upsert_direct_chats([("seller", "direct-seller")], now)
    _configure_market(repository, now)

    started = repository.start_dark_market_draft("seller", now)
    invalid = repository.advance_dark_market_draft("seller", "名" * 31, now)
    resumed = repository.start_dark_market_draft("seller", now + timedelta(minutes=1))

    assert started.status == "started"
    assert invalid.status == "invalid"
    assert invalid.step == "name"
    assert resumed.status == "resumed"
    assert resumed.step == "name"
    assert repository.direct_inbound_chatroom_ids(now) == ("direct-seller",)
    assert repository.direct_inbound_chatroom_ids(
        now + timedelta(minutes=30)
    ) == ()


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


def test_dark_market_group_notices_wait_for_random_event_but_private_refund_does_not(
    repository, now
) -> None:
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=dark-market-room", now
    )
    repository.create_random_event_scene(
        "会议室", "报名", ["正式开始。"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(
        ["18:00"],
        "可选身份：{可选身份}",
        1,
        5,
    )
    repository.run_random_event_jobs(now)
    listing = _active_listing(repository, now)

    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )
    repository.place_dark_market_bid(
        "buyer-b", listing.public_number, 25,
        _inbound_id(repository, "buyer-b", "/报价 1 25", now), now,
    )

    with repository._session() as session:
        group_notices = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "group",
                    OutboundRecord.text.like("暗网%"),
                )
            )
        )
        private_refunds = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "direct",
                    OutboundRecord.destination_chatroom_id == "direct-buyer-a",
                    OutboundRecord.text.like("%冻结的 20 摸鱼币已退回%"),
                )
            )
        )
    assert group_notices == []
    assert len(private_refunds) == 1
    assert _balance(repository, "buyer-a") == 100

    repository.run_random_event_jobs(now + timedelta(minutes=1))

    with repository._session() as session:
        released_notices = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "group",
                    OutboundRecord.text.like("暗网%"),
                )
            )
        )
    assert released_notices == ["暗网商品 #1 出现新的最高报价：25 摸鱼币。"]


def test_dark_market_public_notice_checks_the_gameplay_gate(
    repository, now, monkeypatch
) -> None:
    listing = _active_listing(repository, now)
    order = []

    def record_balance_write(target, value, oldvalue, initiator):
        order.append("balance")

    def reject_unlocked_notice(session):
        order.append("gate")
        raise RuntimeError("gameplay gate checked")

    monkeypatch.setattr(repository, "_lock_gameplay_gate", reject_unlocked_notice)
    event.listen(UserRecord.balance, "set", record_balance_write)

    try:
        with pytest.raises(RuntimeError, match="gameplay gate checked"):
            repository.place_dark_market_bid(
                "buyer-a", listing.public_number, 20,
                _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
            )
    finally:
        event.remove(UserRecord.balance, "set", record_balance_write)

    assert order == ["gate"]


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


def test_auction_end_holds_funds_and_privately_exchanges_counterpart_identity(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )

    repository.run_dark_market_jobs(listing.ends_at)

    assert _balance(repository, "buyer-a") == 79
    assert _balance(repository, "seller") == 100
    with repository._session() as session:
        stored = session.scalar(
            select(DarkMarketListingRecord).where(
                DarkMarketListingRecord.id == listing.id
            )
        )
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
        direct_messages = list(
            session.scalars(
                select(OutboundRecord)
                .where(OutboundRecord.delivery_kind == "direct")
                .order_by(OutboundRecord.destination_chatroom_id)
            )
        )
    assert stored is not None
    assert stored.state == "awaiting_receipt"
    assert stored.final_amount == 21
    assert stored.fee_amount is None
    assert stored.receipt_started_at == listing.ends_at
    assert stored.receipt_deadline == listing.ends_at + timedelta(hours=72)
    assert stored.receipt_resolved_at is None
    assert disclosure is None
    assert len(direct_messages) == 2
    seller_message = next(
        message
        for message in direct_messages
        if message.destination_chatroom_id == "direct-seller"
    )
    buyer_message = next(
        message
        for message in direct_messages
        if message.destination_chatroom_id == "direct-buyer-a"
    )
    assert "买家甲（#0002）" in seller_message.text
    assert "真实卖家（#0001）" in buyer_message.text
    assert "/确认收货 1" in buyer_message.text
    assert "/投诉 1" in buyer_message.text
    assert repository.direct_inbound_chatroom_ids(listing.ends_at) == (
        "direct-buyer-a",
    )


def test_buyer_confirmation_pays_seller_fee_and_starts_disclosure(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    confirmed_at = _confirm_listing(repository, listing, now)

    assert _balance(repository, "buyer-a") == 79
    assert _balance(repository, "seller") == 119
    with repository._session() as session:
        stored = session.get(DarkMarketListingRecord, listing.id)
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
    assert stored.receipt_resolved_at == confirmed_at
    assert set(ledger) == {(21, "dark_market_sale_income"), (-2, "dark_market_sale_fee")}
    assert disclosure is not None
    assert disclosure.deadline == confirmed_at + timedelta(minutes=10)


def test_setting_disclosure_duration_recalculates_pending_deadline_from_created_at(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    confirmed_at = _confirm_listing(repository, listing, now)
    settings = repository.get_dark_market_settings()

    repository.set_dark_market_settings(
        enabled=settings.enabled,
        announcement_group_id=settings.announcement_group_id,
        duration_hours=settings.duration_hours,
        fee_percent=settings.fee_percent,
        disclosure_duration_value=2,
        disclosure_duration_unit="hour",
        rank_limits={
            limit.rank_id: limit.daily_limit for limit in settings.rank_limits
        },
        expected_version=settings.version,
        now=confirmed_at + timedelta(minutes=5),
    )

    with repository._session() as session:
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert disclosure is not None
    assert disclosure.state == "pending"
    assert disclosure.deadline == confirmed_at + timedelta(hours=2)


def test_new_disclosure_uses_configured_duration_and_dynamic_message(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    settings = repository.get_dark_market_settings()
    repository.set_dark_market_settings(
        enabled=settings.enabled,
        announcement_group_id=settings.announcement_group_id,
        duration_hours=settings.duration_hours,
        fee_percent=settings.fee_percent,
        disclosure_duration_value=6,
        disclosure_duration_unit="hour",
        rank_limits={
            limit.rank_id: limit.daily_limit for limit in settings.rank_limits
        },
        expected_version=settings.version,
        now=now,
    )
    confirmed_at = _confirm_listing(repository, listing, now)

    with repository._session() as session:
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
        notices = tuple(
            session.scalars(
                select(OutboundRecord).where(
                    OutboundRecord.delivery_kind == "direct",
                    OutboundRecord.text.contains("/公开"),
                )
            )
        )
    assert disclosure is not None
    assert disclosure.deadline == confirmed_at + timedelta(hours=6)
    assert len(notices) == 2
    assert all("请在 6 小时内" in notice.text for notice in notices)


def test_shortening_disclosure_duration_immediately_anonymizes_expired_pending(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    confirmed_at = _confirm_listing(repository, listing, now)
    settings = repository.get_dark_market_settings()
    changed_at = confirmed_at + timedelta(minutes=5)

    repository.set_dark_market_settings(
        enabled=settings.enabled,
        announcement_group_id=settings.announcement_group_id,
        duration_hours=settings.duration_hours,
        fee_percent=settings.fee_percent,
        disclosure_duration_value=1,
        disclosure_duration_unit="minute",
        rank_limits={
            limit.rank_id: limit.daily_limit for limit in settings.rank_limits
        },
        expected_version=settings.version,
        now=changed_at,
    )

    with repository._session() as session:
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert disclosure is not None
    assert disclosure.deadline == confirmed_at + timedelta(minutes=1)
    assert disclosure.state == "anonymous"
    assert disclosure.finished_at == changed_at


@pytest.mark.parametrize("final_state", ["revealed", "anonymous"])
def test_setting_disclosure_duration_does_not_change_finished_disclosures(
    repository, now, final_state
) -> None:
    listing = _active_listing(repository, now)
    confirmed_at = _confirm_listing(repository, listing, now)
    finished_at = confirmed_at + timedelta(minutes=2)
    with repository.transaction():
        with repository._session() as session:
            disclosure = session.scalar(
                select(DarkMarketDisclosureRecord).where(
                    DarkMarketDisclosureRecord.listing_id == listing.id
                )
            )
            assert disclosure is not None
            original_deadline = disclosure.deadline
            disclosure.state = final_state
            disclosure.finished_at = finished_at
    settings = repository.get_dark_market_settings()

    repository.set_dark_market_settings(
        enabled=settings.enabled,
        announcement_group_id=settings.announcement_group_id,
        duration_hours=settings.duration_hours,
        fee_percent=settings.fee_percent,
        disclosure_duration_value=30,
        disclosure_duration_unit="day",
        rank_limits={
            limit.rank_id: limit.daily_limit for limit in settings.rank_limits
        },
        expected_version=settings.version,
        now=finished_at + timedelta(minutes=1),
    )

    with repository._session() as session:
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert disclosure is not None
    assert disclosure.state == final_state
    assert disclosure.deadline == original_deadline
    assert disclosure.finished_at == finished_at


def test_buyer_complaint_waits_for_board_review_without_moving_money(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    with repository.transaction():
        with repository._session() as session:
            seller = session.scalar(
                select(UserRecord).where(UserRecord.platform_id == "seller")
            )
            assert seller is not None
            seller.balance = 5
    complained_at = listing.ends_at + timedelta(hours=1)

    result = repository.resolve_dark_market_receipt(
        "buyer-a",
        listing.public_number,
        "complain",
        _inbound_id(repository, "buyer-a", "/投诉 1", complained_at),
        complained_at,
    )

    assert result.status == "complaint_pending"
    assert _balance(repository, "buyer-a") == 79
    assert _balance(repository, "seller") == 5
    with repository._session() as session:
        stored = session.get(DarkMarketListingRecord, listing.id)
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
        ledger = set(
            session.execute(
                select(
                    BalanceTransactionRecord.amount,
                    BalanceTransactionRecord.source,
                ).where(
                    BalanceTransactionRecord.source.like("dark_market_complaint_%")
                )
            ).all()
        )
        notices = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "group",
                    OutboundRecord.text.like("%投诉审核%"),
                )
            )
        )
    assert stored is not None
    assert stored.state == "complaint_pending"
    assert stored.complaint_requested_at == complained_at
    assert stored.complaint_reviewed_at is None
    assert stored.complaint_reviewed_by is None
    assert stored.complaint_decision is None
    assert stored.receipt_resolved_at is None
    assert stored.finished_at is None
    assert stored.fee_amount is None
    assert disclosure is None
    assert ledger == set()
    assert len(notices) == 1
    assert "商品 #1 进入投诉审核" in notices[0]
    assert "真实卖家" not in notices[0]
    assert "买家甲" not in notices[0]


def test_board_approves_complaint_refunds_buyer_and_fines_seller(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    with repository.transaction():
        with repository._session() as session:
            seller = session.scalar(
                select(UserRecord).where(UserRecord.platform_id == "seller")
            )
            assert seller is not None
            seller.balance = 5
    complained_at = listing.ends_at + timedelta(hours=1)
    repository.resolve_dark_market_receipt(
        "buyer-a", listing.public_number, "complain",
        _inbound_id(repository, "buyer-a", "/投诉 1", complained_at),
        complained_at,
    )
    reviewed_at = complained_at + timedelta(minutes=10)

    result = repository.review_dark_market_complaint(
        listing.id, True, "董事甲", reviewed_at
    )

    assert result.status == "approved"
    assert _balance(repository, "buyer-a") == 100
    assert _balance(repository, "seller") == -16
    with repository._session() as session:
        stored = session.get(DarkMarketListingRecord, listing.id)
        ledger = set(
            session.execute(
                select(
                    BalanceTransactionRecord.amount,
                    BalanceTransactionRecord.source,
                ).where(
                    BalanceTransactionRecord.source.like("dark_market_complaint_%")
                )
            ).all()
        )
        notice = session.scalar(
            select(OutboundRecord.text)
            .where(OutboundRecord.text.like("%公开通报批评%"))
            .order_by(OutboundRecord.created_at.desc())
        )
    assert stored is not None
    assert stored.state == "complained"
    assert stored.complaint_reviewed_at == reviewed_at
    assert stored.complaint_reviewed_by == "董事甲"
    assert stored.complaint_decision == "approved"
    assert stored.receipt_resolved_at == reviewed_at
    assert ledger == {
        (21, "dark_market_complaint_refund"),
        (-21, "dark_market_complaint_penalty"),
    }
    assert notice is not None
    assert "真实卖家（#0001）" in notice
    assert "买家甲" not in notice
    detail = repository.get_dark_market_listing(listing.id)
    assert detail is not None
    assert detail.complaint_refund_amount == 21
    assert detail.complaint_penalty_amount == 21
    assert {
        (
            transaction.platform_id,
            transaction.amount,
            transaction.source,
        )
        for transaction in detail.balance_transactions
    } == {
        ("buyer-a", -21, "dark_market_bid_hold"),
        ("buyer-a", 21, "dark_market_complaint_refund"),
        ("seller", -21, "dark_market_complaint_penalty"),
    }


def test_board_rejects_complaint_and_settles_sale(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    complained_at = listing.ends_at + timedelta(hours=1)
    repository.resolve_dark_market_receipt(
        "buyer-a", listing.public_number, "complain",
        _inbound_id(repository, "buyer-a", "/投诉 1", complained_at),
        complained_at,
    )
    reviewed_at = complained_at + timedelta(minutes=10)

    result = repository.review_dark_market_complaint(
        listing.id, False, "超级管理员", reviewed_at
    )

    assert result.status == "rejected"
    assert _balance(repository, "buyer-a") == 79
    assert _balance(repository, "seller") == 119
    with repository._session() as session:
        stored = session.get(DarkMarketListingRecord, listing.id)
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
        ledger = set(
            session.execute(
                select(
                    BalanceTransactionRecord.amount,
                    BalanceTransactionRecord.source,
                ).where(BalanceTransactionRecord.source.like("dark_market_sale_%"))
            ).all()
        )
        direct_notices = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "direct",
                    OutboundRecord.text.like("%投诉已被驳回%"),
                )
            )
        )
    assert stored is not None
    assert stored.state == "sold"
    assert stored.fee_amount == 2
    assert stored.complaint_reviewed_at == reviewed_at
    assert stored.complaint_reviewed_by == "超级管理员"
    assert stored.complaint_decision == "rejected"
    assert stored.receipt_resolved_at == reviewed_at
    assert ledger == {
        (21, "dark_market_sale_income"),
        (-2, "dark_market_sale_fee"),
    }
    assert disclosure is not None
    assert len(direct_notices) == 2
    assert all("交易已结算" in text for text in direct_notices)
    assert all("已确认收货" not in text for text in direct_notices)
    detail = repository.get_dark_market_listing(listing.id)
    assert detail is not None
    assert detail.complaint_refund_amount is None
    assert detail.complaint_penalty_amount is None
    assert {
        (transaction.platform_id, transaction.amount, transaction.source)
        for transaction in detail.balance_transactions
    } == {
        ("buyer-a", -21, "dark_market_bid_hold"),
        ("seller", 21, "dark_market_sale_income"),
        ("seller", -2, "dark_market_sale_fee"),
    }


def test_pending_complaint_never_auto_confirms_and_review_is_one_way(
    repository, now
) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    complained_at = listing.ends_at + timedelta(hours=1)
    repository.resolve_dark_market_receipt(
        "buyer-a", listing.public_number, "complain",
        _inbound_id(repository, "buyer-a", "/投诉 1", complained_at),
        complained_at,
    )

    repository.run_dark_market_jobs(listing.ends_at + timedelta(days=10))
    assert _balance(repository, "buyer-a") == 79
    assert _balance(repository, "seller") == 100

    first = repository.review_dark_market_complaint(
        listing.id, True, "董事甲", complained_at + timedelta(days=10)
    )
    second = repository.review_dark_market_complaint(
        listing.id, False, "董事乙", complained_at + timedelta(days=10, minutes=1)
    )

    assert first.status == "approved"
    assert second.status == "already_reviewed"
    assert _balance(repository, "buyer-a") == 100
    assert _balance(repository, "seller") == 79


def test_receipt_auto_confirms_at_exact_72_hour_deadline(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 21,
        _inbound_id(repository, "buyer-a", "/报价 1 21", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    deadline = listing.ends_at + timedelta(hours=72)

    repository.run_dark_market_jobs(deadline - timedelta(microseconds=1))
    assert _balance(repository, "seller") == 100
    repository.run_dark_market_jobs(deadline)

    assert _balance(repository, "seller") == 119
    with repository._session() as session:
        stored = session.get(DarkMarketListingRecord, listing.id)
        disclosure = session.scalar(
            select(DarkMarketDisclosureRecord).where(
                DarkMarketDisclosureRecord.listing_id == listing.id
            )
        )
    assert stored is not None
    assert stored.state == "sold"
    assert stored.receipt_resolved_at == deadline
    assert disclosure is not None
    assert disclosure.deadline == deadline + timedelta(minutes=10)


def test_receipt_requires_buyer_and_item_number_when_multiple_are_pending(
    repository, now
) -> None:
    first = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", first.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )
    repository.create_user("seller-b", "卖家乙", now, 100)
    repository.upsert_direct_chats([("seller-b", "direct-seller-b")], now)
    _complete_draft(repository, "seller-b", now)
    second_result = repository.confirm_dark_market_listing("seller-b", uuid4(), now)
    assert second_result.listing is not None
    second = second_result.listing
    repository.place_dark_market_bid(
        "buyer-a", second.public_number, 22,
        _inbound_id(repository, "buyer-a", f"/报价 {second.public_number} 22", now),
        now,
    )
    repository.run_dark_market_jobs(first.ends_at)

    choose = repository.resolve_dark_market_receipt(
        "buyer-a", None, "confirm",
        _inbound_id(repository, "buyer-a", "/确认收货", first.ends_at),
        first.ends_at,
    )
    unauthorized = repository.resolve_dark_market_receipt(
        "buyer-b", first.public_number, "confirm",
        _inbound_id(repository, "buyer-b", "/确认收货 1", first.ends_at),
        first.ends_at,
    )
    confirmed = repository.resolve_dark_market_receipt(
        "buyer-a", first.public_number, "confirm",
        _inbound_id(repository, "buyer-a", "/确认收货 1", first.ends_at),
        first.ends_at,
    )
    repeated = repository.resolve_dark_market_receipt(
        "buyer-a", first.public_number, "complain",
        _inbound_id(repository, "buyer-a", "/投诉 1", first.ends_at),
        first.ends_at,
    )

    assert choose.status == "choose_listing"
    assert choose.candidates == (first.public_number, second.public_number)
    assert unauthorized.status == "not_buyer"
    assert confirmed.status == "confirmed"
    assert repeated.status == "already_resolved"


def test_receipt_direct_room_expires_at_exact_deadline(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "buyer-a", listing.public_number, 20,
        _inbound_id(repository, "buyer-a", "/报价 1 20", now), now,
    )
    repository.run_dark_market_jobs(listing.ends_at)
    deadline = listing.ends_at + timedelta(hours=72)

    assert repository.direct_inbound_chatroom_ids(
        deadline - timedelta(microseconds=1)
    ) == ("direct-buyer-a",)
    assert repository.direct_inbound_chatroom_ids(deadline) == ()


def test_seller_self_sale_still_pays_fee(repository, now) -> None:
    listing = _active_listing(repository, now)
    repository.place_dark_market_bid(
        "seller", listing.public_number, 20,
        _inbound_id(repository, "seller", "/报价 1 20", now), now,
    )

    repository.run_dark_market_jobs(listing.ends_at)

    with repository._session() as session:
        direct_messages = list(
            session.scalars(
                select(OutboundRecord).where(
                    OutboundRecord.delivery_kind == "direct"
                )
            )
        )
    assert len(direct_messages) == 1
    assert "自己的商品" in direct_messages[0].text

    repository.resolve_dark_market_receipt(
        "seller",
        listing.public_number,
        "confirm",
        _inbound_id(repository, "seller", "/确认收货 1", listing.ends_at),
        listing.ends_at,
    )

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
    repository.resolve_dark_market_receipt(
        "buyer-a",
        listing.public_number,
        "confirm",
        _inbound_id(repository, "buyer-a", "/确认收货 1", listing.ends_at),
        listing.ends_at,
    )

    assert set(repository.direct_inbound_chatroom_ids(listing.ends_at)) == {
        "direct-seller",
        "direct-buyer-a",
    }
    assert repository.direct_inbound_chatroom_ids(
        listing.ends_at + timedelta(minutes=10)
    ) == ()

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
    assert repository.direct_inbound_chatroom_ids(listing.ends_at) == ()
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
    repository.resolve_dark_market_receipt(
        "buyer-a",
        listing.public_number,
        "confirm",
        _inbound_id(repository, "buyer-a", "/确认收货 1", listing.ends_at),
        listing.ends_at,
    )

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
    assert stored.state == "awaiting_receipt"

    repository.run_daily_jobs(listing.ends_at + timedelta(hours=72))

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
