from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .group_games import GROUP_GAME_TYPES


BEIJING = ZoneInfo("Asia/Shanghai")
PRIMARY_GROUP_CHAT_ID = UUID("00000000-0000-0000-0000-000000000001")


def beijing_now() -> datetime:
    return datetime.now(BEIJING)


class BeijingDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(BEIJING)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=BEIJING)
        return value.astimezone(BEIJING)


class Base(DeclarativeBase):
    pass


class GroupChatRecord(Base):
    __tablename__ = "group_chats"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    chat_url: Mapped[str | None] = mapped_column(Text, unique=True)
    chatroom_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    listening_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    games_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled_game_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: list(GROUP_GAME_TYPES)
    )
    random_events_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    announcements_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adult_shop_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    performances_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class GroupChatRuntimeStateRecord(Base):
    __tablename__ = "group_chat_runtime_states"

    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), primary_key=True
    )
    connection_state: Mapped[str] = mapped_column(String(16), nullable=False)
    last_connected_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    last_inbound_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    last_outbound_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    last_error_summary: Mapped[str | None] = mapped_column(String(512))
    worker_id: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class InboundRecord(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        Index(
            "ux_inbound_messages_group_platform_message_id",
            "group_chat_id",
            "platform_message_id",
            unique=True,
            sqlite_where=text("source_type = 'group'"),
            postgresql_where=text("source_type = 'group'"),
        ),
        Index(
            "ux_inbound_messages_direct_platform_message_id",
            "chatroom_id",
            "platform_message_id",
            unique=True,
            sqlite_where=text("source_type = 'direct'"),
            postgresql_where=text("source_type = 'direct'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_platform_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(16), default="text", server_default="text", nullable=False
    )
    image_url: Mapped[str | None] = mapped_column(Text)
    image_alt: Mapped[str | None] = mapped_column(String(512))
    image_width: Mapped[int | None] = mapped_column(Integer)
    image_height: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="accepted", nullable=False)
    ai_memory_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(16), default="group", nullable=False
    )
    chatroom_id: Mapped[str | None] = mapped_column(String(255))
    group_chat_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class CommandDefinitionRecord(Base):
    __tablename__ = "command_definitions"

    command: Mapped[str] = mapped_column(String(32), primary_key=True)
    syntax: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class CommandReplyTemplateRecord(Base):
    __tablename__ = "command_reply_templates"
    __table_args__ = (UniqueConstraint("command", "scenario"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    command: Mapped[str] = mapped_column(String(32), nullable=False)
    scenario: Mapped[str] = mapped_column(String(64), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )


class GameSettingsRecord(Base):
    __tablename__ = "game_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    currency_name: Mapped[str] = mapped_column(String(12), nullable=False)
    onboarding_bonus: Mapped[int] = mapped_column(Integer, nullable=False)
    checkin_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    weekly_attendance_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    company_story_novel_url: Mapped[str | None] = mapped_column(String(4096))


class ProfileSettingsRecord(Base):
    __tablename__ = "profile_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    edit_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    shared_labor: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ActivityLevelRuleRecord(Base):
    __tablename__ = "activity_level_rules"

    level: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)


class IncomeReportScheduleRecord(Base):
    __tablename__ = "income_report_schedules"

    report_time: Mapped[str] = mapped_column(String(5), primary_key=True)


class RandomEventSettingsRecord(Base):
    __tablename__ = "random_event_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    start_time: Mapped[str] = mapped_column(String(5), nullable=False)
    end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    events_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    schedule_times: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    signup_notice_template: Mapped[str] = mapped_column(Text, nullable=False)
    signup_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reminder_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    signup_allowed_commands: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    in_progress_allowed_commands: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    blocked_message: Mapped[str] = mapped_column(Text, nullable=False)
    submission_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    submission_draft_timeout_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    submission_max_participants: Mapped[int] = mapped_column(
        Integer, nullable=False, default=99, server_default="99"
    )
    submission_default_target_rounds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    submission_default_event_reward: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6, server_default="6"
    )
    global_completion_reward: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6, server_default="6"
    )
    submission_approval_reward: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    tipping_duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120, server_default="120"
    )


class HideAndSeekSettingsRecord(Base):
    __tablename__ = "hide_and_seek_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    entry_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    win_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False)


class HideAndSeekSceneRecord(Base):
    __tablename__ = "hide_and_seek_scenes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class UndercoverWordSetRecord(Base):
    __tablename__ = "undercover_word_sets"
    __table_args__ = (UniqueConstraint("civilian_word", "undercover_word"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    civilian_word: Mapped[str] = mapped_column(String(64), nullable=False)
    undercover_word: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class UndercoverSettingsRecord(Base):
    __tablename__ = "undercover_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    vote_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    whiteboard_win_remaining: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False
    )
    signup_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )


class UndercoverRoleRuleRecord(Base):
    __tablename__ = "undercover_role_rules"

    player_count: Mapped[int] = mapped_column(Integer, primary_key=True)
    civilian_count: Mapped[int] = mapped_column(Integer, nullable=False)
    undercover_count: Mapped[int] = mapped_column(Integer, nullable=False)
    whiteboard_count: Mapped[int] = mapped_column(Integer, nullable=False)


class DirectChatRecord(Base):
    __tablename__ = "direct_chats"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform_user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    chatroom_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class UndercoverSessionRecord(Base):
    __tablename__ = "undercover_sessions"
    __table_args__ = (
        Index(
            "ux_undercover_one_active_session",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(32))
    target_player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signup_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    await_continue_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class UndercoverSessionMemberRecord(Base):
    __tablename__ = "undercover_session_members"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("undercover_sessions.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    is_original: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    left_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    leave_after_round: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class UndercoverGameRecord(Base):
    __tablename__ = "undercover_games"
    __table_args__ = (UniqueConstraint("session_id", "round_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("undercover_sessions.id"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    current_vote_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    civilian_word: Mapped[str] = mapped_column(String(64), nullable=False)
    undercover_word: Mapped[str] = mapped_column(String(64), nullable=False)
    vote_seconds_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    whiteboard_win_remaining_snapshot: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    vote_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class UndercoverGamePlayerRecord(Base):
    __tablename__ = "undercover_game_players"
    __table_args__ = (
        UniqueConstraint("game_id", "user_id"),
        UniqueConstraint("game_id", "seat_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("undercover_games.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    seat_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    card_delivery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    card_outbound_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id"), unique=True
    )


class UndercoverVoteRecord(Base):
    __tablename__ = "undercover_votes"
    __table_args__ = (UniqueConstraint("game_id", "round_number", "voter_user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("undercover_games.id"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    voter_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class UndercoverAbstentionRecord(Base):
    __tablename__ = "undercover_abstentions"
    __table_args__ = (
        UniqueConstraint("game_id", "round_number", "player_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("undercover_games.id"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    player_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class BlameGameSettingsRecord(Base):
    __tablename__ = "blame_game_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    signup_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


class BlameGameDurationRuleRecord(Base):
    __tablename__ = "blame_game_duration_rules"

    player_count: Mapped[int] = mapped_column(Integer, primary_key=True)
    minimum_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


class BlameIncidentCardRecord(Base):
    __tablename__ = "blame_incident_cards"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class BlameGameRecord(Base):
    __tablename__ = "blame_games"
    __table_args__ = (
        Index(
            "ux_blame_game_one_active",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(32))
    creator_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    signup_deadline: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    incident_card_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("blame_incident_cards.id", ondelete="SET NULL")
    )
    incident_name: Mapped[str | None] = mapped_column(String(128))
    incident_description: Mapped[str | None] = mapped_column(Text)
    keywords_snapshot: Mapped[list[str] | None] = mapped_column(JSON)
    total_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    explosion_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    turn_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    current_holder_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    previous_holder_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    last_announced_temperature: Mapped[str | None] = mapped_column(String(32))
    loser_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    settlement_reason: Mapped[str | None] = mapped_column(String(32))
    settlement_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class BlameGamePlayerRecord(Base):
    __tablename__ = "blame_game_players"
    __table_args__ = (
        UniqueConstraint("game_id", "user_id"),
        UniqueConstraint("game_id", "seat_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("blame_games.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    signup_order: Mapped[int] = mapped_column(Integer, nullable=False)
    seat_number: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    guarantee_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    guarantee_state: Mapped[str] = mapped_column(String(16), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class BlameGameTransferRecord(Base):
    __tablename__ = "blame_game_transfers"
    __table_args__ = (UniqueConstraint("game_id", "normalized_reason"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("blame_games.id"), nullable=False)
    from_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class BlameGameDailyStartRecord(Base):
    __tablename__ = "blame_game_daily_starts"
    __table_args__ = (UniqueConstraint("user_id", "play_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RedPacketSettingsRecord(Base):
    __tablename__ = "red_packet_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    expiry_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    empty_probability_percent: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )


class RedPacketRecord(Base):
    __tablename__ = "red_packets"
    __table_args__ = (
        Index(
            "ux_red_packet_one_active",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    active_key: Mapped[str | None] = mapped_column(String(32))
    issuer_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    has_empty: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    refunded_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RedPacketShareRecord(Base):
    __tablename__ = "red_packet_shares"
    __table_args__ = (
        UniqueConstraint("packet_id", "display_order"),
        UniqueConstraint("packet_id", "claimant_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    packet_id: Mapped[UUID] = mapped_column(
        ForeignKey("red_packets.id"), nullable=False
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    claimant_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class RedPacketDailyStartRecord(Base):
    __tablename__ = "red_packet_daily_starts"
    __table_args__ = (UniqueConstraint("user_id", "play_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class NumberBombSettingsRecord(Base):
    __tablename__ = "number_bomb_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    inactivity_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    signup_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )
    reminder_interval_seconds: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False
    )


class NumberBombGameRecord(Base):
    __tablename__ = "number_bomb_games"
    __table_args__ = (
        Index(
            "ux_number_bomb_one_active",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
        CheckConstraint(
            "mode IN ('standard', 'points_tournament')",
            name="ck_number_bomb_game_mode",
        ),
        CheckConstraint(
            "maximum_rounds IN (0, 12)",
            name="ck_number_bomb_game_maximum_rounds",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    active_key: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(32), default="standard", server_default="standard", nullable=False
    )
    maximum_rounds: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    target_player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    signup_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    next_reminder_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    skip_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finish_reason: Mapped[str | None] = mapped_column(String(64))


class NumberBombMemberRecord(Base):
    __tablename__ = "number_bomb_members"
    __table_args__ = (UniqueConstraint("game_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("number_bomb_games.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    roster_order: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    queued_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    total_points: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    retired_at_round: Mapped[int | None] = mapped_column(Integer)


class NumberBombRoundRecord(Base):
    __tablename__ = "number_bomb_rounds"
    __table_args__ = (
        UniqueConstraint("game_id", "round_number", "attempt_number"),
        CheckConstraint(
            "multiplier_tenths IN (8, 9, 10, 11, 12)",
            name="ck_number_bomb_round_multiplier_tenths",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("number_bomb_games.id"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    punishment_type: Mapped[str] = mapped_column(String(16), nullable=False)
    multiplier_tenths: Mapped[int] = mapped_column(
        Integer, default=8, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    total: Mapped[int | None] = mapped_column(Integer)
    player_count: Mapped[int] = mapped_column(Integer, nullable=False)
    target_numerator: Mapped[int | None] = mapped_column(Integer)
    target_denominator: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class NumberBombRoundPlayerRecord(Base):
    __tablename__ = "number_bomb_round_players"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id"),
        CheckConstraint(
            "result_reason IS NULL OR result_reason IN ('reported', 'skipped', 'retired')",
            name="ck_number_bomb_round_player_result_reason",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    round_id: Mapped[UUID] = mapped_column(
        ForeignKey("number_bomb_rounds.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_number: Mapped[int | None] = mapped_column(Integer)
    deviation_numerator: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(String(16))
    skipped_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    competition_rank: Mapped[int | None] = mapped_column(Integer)
    round_points: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    result_reason: Mapped[str | None] = mapped_column(String(32))


class NeverHaveIEverSettingsRecord(Base):
    __tablename__ = "never_have_i_ever_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    signup_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False
    )
    statement_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )
    response_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class NeverHaveIEverGameRecord(Base):
    __tablename__ = "never_have_i_ever_games"
    __table_args__ = (
        Index(
            "ux_never_have_i_ever_one_active",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
        CheckConstraint(
            "state IN ('signup', 'awaiting_statement', 'awaiting_responses', "
            "'free_punishment', 'completed', 'cancelled', 'expired', "
            "'forced_ended')",
            name="ck_never_have_i_ever_game_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    host_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    active_key: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    initial_player_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    current_speaker_order: Mapped[int | None] = mapped_column(Integer)
    round_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signup_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    statement_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    response_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    free_punishment_started_at: Mapped[datetime | None] = mapped_column(
        BeijingDateTime
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finish_reason: Mapped[str | None] = mapped_column(String(64))


class NeverHaveIEverPlayerRecord(Base):
    __tablename__ = "never_have_i_ever_players"
    __table_args__ = (
        UniqueConstraint("game_id", "user_id"),
        UniqueConstraint("game_id", "roster_order"),
        CheckConstraint("hearts >= 0", name="ck_never_have_i_ever_hearts"),
        CheckConstraint(
            "state IN ('signup', 'active', 'eliminated', 'withdrawn')",
            name="ck_never_have_i_ever_player_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("never_have_i_ever_games.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    roster_order: Mapped[int] = mapped_column(Integer, nullable=False)
    hearts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    eliminated_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    elimination_reason: Mapped[str | None] = mapped_column(String(64))


class NeverHaveIEverRoundRecord(Base):
    __tablename__ = "never_have_i_ever_rounds"
    __table_args__ = (
        UniqueConstraint("game_id", "sequence"),
        CheckConstraint(
            "state IN ('awaiting_statement', 'awaiting_responses', 'settled', "
            "'statement_timeout')",
            name="ck_never_have_i_ever_round_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("never_have_i_ever_games.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    statement: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    statement_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    response_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    settled_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    statement_timed_out: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class NeverHaveIEverResponseRecord(Base):
    __tablename__ = "never_have_i_ever_responses"
    __table_args__ = (
        UniqueConstraint("round_id", "user_id"),
        CheckConstraint(
            "choice IN ('deduct', 'keep', 'timeout_deduct')",
            name="ck_never_have_i_ever_response_choice",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    round_id: Mapped[UUID] = mapped_column(
        ForeignKey("never_have_i_ever_rounds.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    choice: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class KingGameSettingsRecord(Base):
    __tablename__ = "king_game_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    king_phase_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=500, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class KingGameRecord(Base):
    __tablename__ = "king_games"
    __table_args__ = (
        Index(
            "ux_king_game_one_active",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
        CheckConstraint(
            "state IN ('signup', 'awaiting_reveal', 'revealed', 'completed', "
            "'cancelled', 'expired', 'forced_ended')",
            name="ck_king_game_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    host_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_king_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    signup_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    king_phase_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    end_after_round: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finish_reason: Mapped[str | None] = mapped_column(String(64))


class KingGamePlayerRecord(Base):
    __tablename__ = "king_game_players"
    __table_args__ = (
        UniqueConstraint("game_id", "user_id"),
        UniqueConstraint("game_id", "roster_order"),
        CheckConstraint(
            "state IN ('signup', 'active', 'withdrawn')",
            name="ck_king_game_player_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("king_games.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    roster_order: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class KingGameRoundRecord(Base):
    __tablename__ = "king_game_rounds"
    __table_args__ = (
        UniqueConstraint("game_id", "sequence"),
        CheckConstraint(
            "state IN ('awaiting_reveal', 'revealed', 'timed_out')",
            name="ck_king_game_round_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("king_games.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    king_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    number_map: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    revealed_numbers: Mapped[list[int] | None] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    revealed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class TexasHoldemSettingsRecord(Base):
    __tablename__ = "texas_holdem_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    minimum_players: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    maximum_players: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    minimum_buy_in: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    maximum_buy_in: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    daily_start_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    signup_timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    action_timeout_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    small_blind_percent: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    big_blind_percent: Mapped[int] = mapped_column(Integer, default=10, nullable=False)


class TexasHoldemGameRecord(Base):
    __tablename__ = "texas_holdem_games"
    __table_args__ = (
        Index(
            "ux_texas_holdem_one_active",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    creator_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    street: Mapped[str | None] = mapped_column(String(16))
    active_key: Mapped[str | None] = mapped_column(String(32))
    buy_in: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_players_snapshot: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )
    maximum_players_snapshot: Mapped[int] = mapped_column(
        Integer, default=9, nullable=False
    )
    daily_start_limit_snapshot: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    start_quota_source: Mapped[str | None] = mapped_column(String(16))
    action_timeout_seconds_snapshot: Mapped[int] = mapped_column(
        Integer, default=120, nullable=False
    )
    small_blind_percent_snapshot: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )
    big_blind_percent_snapshot: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False
    )
    deck: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    board: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    button_seat: Mapped[int | None] = mapped_column(Integer)
    small_blind_seat: Mapped[int | None] = mapped_column(Integer)
    big_blind_seat: Mapped[int | None] = mapped_column(Integer)
    current_seat: Mapped[int | None] = mapped_column(Integer)
    small_blind_amount: Mapped[int | None] = mapped_column(Integer)
    big_blind_amount: Mapped[int | None] = mapped_column(Integer)
    current_bet: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_full_raise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signup_deadline: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    action_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    settlement_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class TexasHoldemPlayerRecord(Base):
    __tablename__ = "texas_holdem_players"
    __table_args__ = (
        UniqueConstraint("game_id", "user_id"),
        UniqueConstraint("game_id", "seat_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("texas_holdem_games.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    seat_number: Mapped[int | None] = mapped_column(Integer)
    hole_cards: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    original_buy_in: Mapped[int] = mapped_column(Integer, nullable=False)
    stack: Mapped[int] = mapped_column(Integer, nullable=False)
    street_contribution: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_contribution: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    acted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raise_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    private_outbound_id: Mapped[UUID | None] = mapped_column(ForeignKey("outbound_messages.id"))
    private_delivery_state: Mapped[str | None] = mapped_column(String(16))
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class TexasHoldemActionRecord(Base):
    __tablename__ = "texas_holdem_actions"
    __table_args__ = (UniqueConstraint("inbound_message_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("texas_holdem_games.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    inbound_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("inbound_messages.id"))
    street: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_amount: Mapped[int | None] = mapped_column(Integer)
    committed_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class TexasHoldemPotRecord(Base):
    __tablename__ = "texas_holdem_pots"
    __table_args__ = (UniqueConstraint("game_id", "pot_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("texas_holdem_games.id"), nullable=False)
    pot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_seats: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    winner_seats: Mapped[list[int] | None] = mapped_column(JSON)


class TexasHoldemDailyStartRecord(Base):
    __tablename__ = "texas_holdem_daily_starts"
    __table_args__ = (UniqueConstraint("user_id", "play_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DarkMarketSettingsRecord(Base):
    __tablename__ = "dark_market_settings"
    __table_args__ = (
        CheckConstraint(
            "duration_hours BETWEEN 1 AND 24", name="ck_dark_market_duration_hours"
        ),
        CheckConstraint(
            "fee_percent BETWEEN 1 AND 100", name="ck_dark_market_fee_percent"
        ),
        CheckConstraint(
            "disclosure_duration_unit IN ('minute', 'hour', 'day')",
            name="ck_dark_market_disclosure_duration_unit",
        ),
        CheckConstraint(
            "(disclosure_duration_unit = 'minute' AND "
            "disclosure_duration_value BETWEEN 1 AND 43200) OR "
            "(disclosure_duration_unit = 'hour' AND "
            "disclosure_duration_value BETWEEN 1 AND 720) OR "
            "(disclosure_duration_unit = 'day' AND "
            "disclosure_duration_value BETWEEN 1 AND 30)",
            name="ck_dark_market_disclosure_duration_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    announcement_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("group_chats.id")
    )
    duration_hours: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    fee_percent: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    disclosure_duration_value: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False
    )
    disclosure_duration_unit: Mapped[str] = mapped_column(
        String(16), default="minute", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DarkMarketRankLimitRecord(Base):
    __tablename__ = "dark_market_rank_limits"
    __table_args__ = (
        CheckConstraint("daily_limit >= -1", name="ck_dark_market_rank_daily_limit"),
    )

    rank_id: Mapped[UUID] = mapped_column(ForeignKey("ranks.id"), primary_key=True)
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False)


class DarkMarketDraftRecord(Base):
    __tablename__ = "dark_market_drafts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_dark_market_drafts_user_id"),
        CheckConstraint(
            "step IN ('name', 'purpose', 'details', 'gender', 'starting_price', 'preview')",
            name="ck_dark_market_draft_step",
        ),
        CheckConstraint(
            "gender IS NULL OR gender IN ('male', 'female', 'private')",
            name="ck_dark_market_draft_gender",
        ),
        CheckConstraint(
            "starting_price IS NULL OR starting_price BETWEEN 1 AND 99999",
            name="ck_dark_market_draft_starting_price",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(30))
    purpose: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[str | None] = mapped_column(String(500))
    gender: Mapped[str | None] = mapped_column(String(16))
    starting_price: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class DarkMarketListingRecord(Base):
    __tablename__ = "dark_market_listings"
    __table_args__ = (
        UniqueConstraint(
            "public_number", name="uq_dark_market_listings_public_number"
        ),
        Index("ix_dark_market_listings_due", "state", "ends_at"),
        Index(
            "ix_dark_market_listings_receipt_due", "state", "receipt_deadline"
        ),
        CheckConstraint(
            "state IN ('active', 'awaiting_receipt', 'complaint_pending', "
            "'sold', 'complained', "
            "'unsold', 'force_delisted')",
            name="ck_dark_market_listing_state",
        ),
        CheckConstraint(
            "gender IN ('male', 'female', 'private')",
            name="ck_dark_market_listing_gender",
        ),
        CheckConstraint(
            "starting_price BETWEEN 1 AND 99999",
            name="ck_dark_market_listing_starting_price",
        ),
        CheckConstraint(
            "complaint_decision IS NULL OR complaint_decision IN ('approved', 'rejected')",
            name="ck_dark_market_listing_complaint_decision",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_number: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    announcement_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[str] = mapped_column(String(500), nullable=False)
    gender: Mapped[str] = mapped_column(String(16), nullable=False)
    starting_price: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_hours_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    fee_percent_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    buyer_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    final_amount: Mapped[int | None] = mapped_column(Integer)
    fee_amount: Mapped[int | None] = mapped_column(Integer)
    receipt_started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    receipt_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    receipt_resolved_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    complaint_requested_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    complaint_reviewed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    complaint_reviewed_by: Mapped[str | None] = mapped_column(String(100))
    complaint_decision: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class DarkMarketBidRecord(Base):
    __tablename__ = "dark_market_bids"
    __table_args__ = (
        UniqueConstraint(
            "inbound_message_id", name="uq_dark_market_bid_inbound"
        ),
        Index("ix_dark_market_bids_listing_created", "listing_id", "created_at"),
        Index(
            "ux_dark_market_one_current_bid",
            "listing_id",
            unique=True,
            sqlite_where=text("state = 'current'"),
            postgresql_where=text("state = 'current'"),
        ),
        CheckConstraint(
            "amount BETWEEN 1 AND 99999", name="ck_dark_market_bid_amount"
        ),
        CheckConstraint(
            "state IN ('current', 'refunded', 'settled')",
            name="ck_dark_market_bid_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("dark_market_listings.id"), nullable=False
    )
    bidder_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    settled_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class DarkMarketDisclosureRecord(Base):
    __tablename__ = "dark_market_disclosures"
    __table_args__ = (
        UniqueConstraint(
            "listing_id", name="uq_dark_market_disclosure_listing"
        ),
        CheckConstraint(
            "state IN ('pending', 'revealed', 'anonymous')",
            name="ck_dark_market_disclosure_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("dark_market_listings.id"), nullable=False
    )
    seller_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    buyer_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    seller_choice: Mapped[bool | None] = mapped_column(Boolean)
    buyer_choice: Mapped[bool | None] = mapped_column(Boolean)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    deadline: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class DarkMarketDeferredNoticeRecord(Base):
    __tablename__ = "dark_market_deferred_notices"

    listing_id: Mapped[UUID] = mapped_column(
        ForeignKey("dark_market_listings.id"), primary_key=True
    )
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class DarkMarketDailyListingRecord(Base):
    __tablename__ = "dark_market_daily_listings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "usage_date", name="uq_dark_market_daily_listing_user_date"
        ),
        CheckConstraint("count >= 0", name="ck_dark_market_daily_listing_count"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DarkMarketNumberCounterRecord(Base):
    __tablename__ = "dark_market_number_counters"
    __table_args__ = (
        CheckConstraint("next_number > 0", name="ck_dark_market_next_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class HideAndSeekDailyPlayRecord(Base):
    __tablename__ = "hide_and_seek_daily_plays"
    __table_args__ = (UniqueConstraint("user_id", "play_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class HideAndSeekGameRecord(Base):
    __tablename__ = "hide_and_seek_games"
    __table_args__ = (
        Index(
            "ux_hide_and_seek_one_selecting_user",
            "group_chat_id",
            "user_id",
            unique=True,
            sqlite_where=text("state = 'selecting'"),
            postgresql_where=text("state = 'selecting'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    candidates: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    selected_number: Mapped[int | None] = mapped_column(Integer)
    patrol_numbers: Mapped[list[int] | None] = mapped_column(JSON)
    entry_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    win_reward: Mapped[int] = mapped_column(Integer, nullable=False)
    choice_deadline: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class MemoryAssessmentSettingsRecord(Base):
    __tablename__ = "memory_assessment_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    single_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    single_recall_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    single_answer_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False
    )
    single_decision_timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False
    )
    duel_recall_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    duel_difficulty_level: Mapped[int] = mapped_column(Integer, nullable=False)
    duel_base_pool: Mapped[int] = mapped_column(Integer, nullable=False)
    duel_wrong_freeze: Mapped[int] = mapped_column(Integer, nullable=False)
    duel_wrong_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    duel_answer_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    duel_signup_timeout_minutes: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )
    character_set: Mapped[str] = mapped_column(Text, nullable=False)


class MemoryAssessmentLevelRuleRecord(Base):
    __tablename__ = "memory_assessment_level_rules"

    level: Mapped[int] = mapped_column(Integer, primary_key=True)
    answer_length: Mapped[int] = mapped_column(Integer, nullable=False)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)


class MemoryAssessmentDailyPlayRecord(Base):
    __tablename__ = "memory_assessment_daily_plays"
    __table_args__ = (UniqueConstraint("user_id", "play_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MemoryAssessmentGameRecord(Base):
    __tablename__ = "memory_assessment_games"
    __table_args__ = (
        Index(
            "ux_memory_assessment_one_active_game",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(32))
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    level: Mapped[int | None] = mapped_column(Integer)
    reward: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    base_pool: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answer_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    signup_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    winner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class MemoryAssessmentParticipantRecord(Base):
    __tablename__ = "memory_assessment_participants"
    __table_args__ = (UniqueConstraint("game_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_assessment_games.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    frozen_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MemoryAssessmentRoundRecord(Base):
    __tablename__ = "memory_assessment_rounds"
    __table_args__ = (UniqueConstraint("game_id", "sequence"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_assessment_games.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    display_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    outbound_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id"), unique=True
    )


class MemoryGuildMatchRecord(Base):
    __tablename__ = "memory_guild_matches"
    __table_args__ = (
        CheckConstraint(
            "planned_series_count BETWEEN 1 AND 20",
            name="ck_memory_guild_planned_series_count",
        ),
        Index(
            "ux_memory_guild_one_active_per_group",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    host_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(32))
    planned_series_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_series_number: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    champion_team_id: Mapped[UUID | None] = mapped_column(Uuid)
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    forced_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class MemoryGuildTeamRecord(Base):
    __tablename__ = "memory_guild_teams"
    __table_args__ = (
        CheckConstraint("slot IN (1, 2)", name="ck_memory_guild_team_slot"),
        UniqueConstraint("match_id", "slot", name="ux_memory_guild_team_match_slot"),
        UniqueConstraint("match_id", "name", name="ux_memory_guild_team_match_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_matches.id"), nullable=False
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64))
    series_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class MemoryGuildMemberRecord(Base):
    __tablename__ = "memory_guild_members"
    __table_args__ = (
        Index(
            "ux_memory_guild_member_match_user",
            "match_id",
            "user_id",
            unique=True,
        ),
        UniqueConstraint(
            "team_id", "roster_order", name="ux_memory_guild_member_team_order"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_matches.id"), nullable=False
    )
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_teams.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    display_name_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    roster_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class MemoryGuildSeriesRecord(Base):
    __tablename__ = "memory_guild_series"
    __table_args__ = (
        UniqueConstraint(
            "match_id", "sequence", name="ux_memory_guild_series_match_sequence"
        ),
        CheckConstraint("sequence >= 1", name="ck_memory_guild_series_sequence"),
        CheckConstraint("win_target >= 1", name="ck_memory_guild_series_win_target"),
        CheckConstraint(
            "maximum_decisive_rounds >= 1",
            name="ck_memory_guild_series_maximum_rounds",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_matches.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    win_target: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_decisive_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_tiebreaker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    team1_member_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_guild_members.id")
    )
    team2_member_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_guild_members.id")
    )
    team1_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    team2_wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    winner_team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_guild_teams.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class MemoryGuildRoundRecord(Base):
    __tablename__ = "memory_guild_rounds"
    __table_args__ = (
        UniqueConstraint(
            "series_id", "sequence", name="ux_memory_guild_round_series_sequence"
        ),
        CheckConstraint("sequence >= 1", name="ck_memory_guild_round_sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_matches.id"), nullable=False
    )
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_series.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    display_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    answer_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    outbound_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id"), unique=True
    )
    winner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    result: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class MemoryGuildAnswerRecord(Base):
    __tablename__ = "memory_guild_answers"
    __table_args__ = (
        Index(
            "ux_memory_guild_answer_platform_message",
            "platform_message_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    round_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_guild_rounds.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    platform_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class RandomEventSceneRecord(Base):
    __tablename__ = "random_event_scenes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    signup_text: Mapped[str] = mapped_column(Text, nullable=False)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)
    target_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class RandomEventSceneSeatRecord(Base):
    __tablename__ = "random_event_scene_seats"
    __table_args__ = (UniqueConstraint("scene_id", "role"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scene_id: Mapped[UUID] = mapped_column(
        ForeignKey("random_event_scenes.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)


class RandomEventSceneOpeningRecord(Base):
    __tablename__ = "random_event_scene_openings"
    __table_args__ = (UniqueConstraint("scene_id", "position"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scene_id: Mapped[UUID] = mapped_column(
        ForeignKey("random_event_scenes.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="未命名事件")
    content: Mapped[str] = mapped_column(Text, nullable=False)


class RandomEventSubmissionCounterRecord(Base):
    __tablename__ = "random_event_submission_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RandomEventSubmissionRecord(Base):
    __tablename__ = "random_event_submissions"
    __table_args__ = (
        Index(
            "ux_random_event_submissions_one_draft",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
            sqlite_where=text("status = 'draft'"),
        ),
        Index(
            "ux_random_event_submissions_one_pending",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        Index("ix_random_event_submissions_status_number", "status", "number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    current_step: Mapped[str] = mapped_column(
        String(64), nullable=False, default="scene_name"
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    target_rounds: Mapped[int | None] = mapped_column(Integer)
    event_reward: Mapped[int | None] = mapped_column(Integer)
    approval_reward: Mapped[int | None] = mapped_column(Integer)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    scene_id: Mapped[UUID | None] = mapped_column(ForeignKey("random_event_scenes.id"))
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    reviewed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    reward_granted_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class RandomEventScheduleRecord(Base):
    __tablename__ = "random_event_schedules"
    __table_args__ = (
        UniqueConstraint("group_chat_id", "event_date", "scheduled_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    scene_name: Mapped[str | None] = mapped_column(String(64))
    event_name: Mapped[str | None] = mapped_column(String(64))
    signup_text: Mapped[str | None] = mapped_column(Text)
    signup_notice_template: Mapped[str | None] = mapped_column(Text)
    formal_opening_text: Mapped[str | None] = mapped_column(Text)
    reward: Mapped[int | None] = mapped_column(Integer)
    target_rounds: Mapped[int | None] = mapped_column(Integer)
    seats: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    pre_notice_sent_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class RandomEventRecord(Base):
    __tablename__ = "random_events"
    __table_args__ = (
        UniqueConstraint("schedule_id"),
        Index(
            "ux_random_events_one_active_group",
            "group_chat_id",
            unique=True,
            sqlite_where=text("state IN ('signup', 'in_progress', 'tipping')"),
            postgresql_where=text("state IN ('signup', 'in_progress', 'tipping')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    schedule_id: Mapped[UUID] = mapped_column(
        ForeignKey("random_event_schedules.id"), nullable=False
    )
    signup_notice_outbound_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id"), index=True
    )
    group_key: Mapped[str] = mapped_column(String(255), default="default", nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    scene_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str | None] = mapped_column(String(64))
    signup_text: Mapped[str] = mapped_column(Text, nullable=False)
    formal_opening_text: Mapped[str] = mapped_column(Text, nullable=False)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)
    target_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    signup_deadline: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    next_reminder_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    started_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    tipping_started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    tipping_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class RandomEventSeatRecord(Base):
    __tablename__ = "random_event_seats"
    __table_args__ = (UniqueConstraint("event_id", "role"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("random_events.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)


class RandomEventParticipantRecord(Base):
    __tablename__ = "random_event_participants"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("random_events.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    left_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    rewarded_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class RandomEventDetailRecord(Base):
    __tablename__ = "random_event_details"
    __table_args__ = (UniqueConstraint("event_id", "position"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("random_events.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class RandomEventTipRecord(Base):
    __tablename__ = "random_event_tips"
    __table_args__ = (
        Index("ix_random_event_tips_event_id", "event_id"),
        UniqueConstraint("inbound_message_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("random_events.id"), nullable=False
    )
    sender_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class PerformanceSettingsRecord(Base):
    __tablename__ = "performance_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    maximum_duration_minutes: Mapped[int] = mapped_column(
        Integer, default=360, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PerformanceReservationRecord(Base):
    __tablename__ = "performance_reservations"
    __table_args__ = (
        Index(
            "ux_performance_reservations_live_date",
            "event_date",
            unique=True,
            sqlite_where=text(
                "state IN ('pending_review', 'approved', 'previewed', 'waiting', "
                "'performing', 'tipping')"
            ),
            postgresql_where=text(
                "state IN ('pending_review', 'approved', 'previewed', 'waiting', "
                "'performing', 'tipping')"
            ),
        ),
        Index(
            "ux_performance_reservations_live_owner",
            "owner_user_id",
            unique=True,
            sqlite_where=text(
                "state IN ('pending_review', 'approved', 'previewed', 'waiting', "
                "'performing', 'tipping')"
            ),
            postgresql_where=text(
                "state IN ('pending_review', 'approved', 'previewed', 'waiting', "
                "'performing', 'tipping')"
            ),
        ),
        Index(
            "ux_performance_reservations_stage_group",
            "group_chat_id",
            unique=True,
            sqlite_where=text("state IN ('performing', 'tipping')"),
            postgresql_where=text("state IN ('performing', 'tipping')"),
        ),
        Index("ix_performance_reservations_state_scheduled", "state", "scheduled_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(50), nullable=False)
    introduction: Mapped[str] = mapped_column(String(500), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text)
    cover_alt: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    pre_notice_sent_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    tipping_started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    tipping_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    maximum_duration_minutes_snapshot: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class PerformanceParticipantRecord(Base):
    __tablename__ = "performance_participants"
    __table_args__ = (
        UniqueConstraint("reservation_id", "user_id"),
        UniqueConstraint("reservation_id", "display_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class PerformanceDraftRecord(Base):
    __tablename__ = "performance_drafts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    current_step: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class PerformanceExtensionRequestRecord(Base):
    __tablename__ = "performance_extension_requests"
    __table_args__ = (
        Index(
            "ux_performance_extension_requests_pending",
            "reservation_id",
            unique=True,
            sqlite_where=text("state = 'pending'"),
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    requester_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_scheduled_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, nullable=False
    )
    proposed_scheduled_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    requested_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class PerformanceMessageRecord(Base):
    __tablename__ = "performance_messages"
    __table_args__ = (
        Index(
            "ix_performance_messages_reservation_created",
            "reservation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class PerformanceTipRecord(Base):
    __tablename__ = "performance_tips"
    __table_args__ = (Index("ix_performance_tips_reservation", "reservation_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    sender_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    recipient_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    platform_nickname: Mapped[str | None] = mapped_column(String(64))
    platform_nickname_synced_at: Mapped[datetime | None] = mapped_column(
        BeijingDateTime
    )
    platform_nickname_attempted_at: Mapped[datetime | None] = mapped_column(
        BeijingDateTime
    )
    employee_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profile_text: Mapped[str] = mapped_column(
        Text, default="", server_default="", nullable=False
    )
    profile_image_url: Mapped[str | None] = mapped_column(Text)
    profile_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    rank_id: Mapped[UUID | None] = mapped_column(ForeignKey("ranks.id"))
    department_id: Mapped[UUID | None] = mapped_column(ForeignKey("departments.id"))
    joined_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class ProfileImageUploadRecord(Base):
    __tablename__ = "profile_image_uploads"
    __table_args__ = (
        Index(
            "ix_profile_image_uploads_claim",
            "status",
            "lease_expires_at",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    temp_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_url: Mapped[str | None] = mapped_column(Text)
    failure_summary: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class EmployeeNumberCounterRecord(Base):
    __tablename__ = "employee_number_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False)


class RankRecord(Base):
    __tablename__ = "ranks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    sort_order: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    level_label: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    promotion_price: Mapped[int] = mapped_column(Integer, nullable=False)
    checkin_reward: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    vote_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    multiplayer_game_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    has_group_management: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_board: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AIAssistantSettingsRecord(Base):
    __tablename__ = "ai_assistant_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trigger_prefixes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["@总监事"]
    )
    persona: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    over_limit_reply: Mapped[str] = mapped_column(Text, nullable=False)
    failure_reply: Mapped[str] = mapped_column(Text, nullable=False)
    max_response_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


class AIRankQuotaRecord(Base):
    __tablename__ = "ai_rank_quotas"

    rank_id: Mapped[UUID] = mapped_column(
        ForeignKey("ranks.id"), primary_key=True
    )
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False)


class DailyAIUsageRecord(Base):
    __tablename__ = "daily_ai_usage"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AIRequestRecord(Base):
    __tablename__ = "ai_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_text: Mapped[str | None] = mapped_column(Text)
    failure_summary: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class AIMemorySettingsRecord(Base):
    __tablename__ = "ai_memory_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    gameplay_guide: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    history_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    max_memory_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=1200)
    batch_message_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20
    )
    max_entries_per_category: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    candidate_expiry_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )


class AIPlayerMemoryRecord(Base):
    __tablename__ = "ai_player_memories"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    memory_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_scanned_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inbound_messages.id")
    )
    pending_message_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AIMemoryJobRecord(Base):
    __tablename__ = "ai_memory_jobs"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    target_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), nullable=False
    )
    target_message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_summary: Mapped[str | None] = mapped_column(String(128))
    available_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AIPlayerImpressionRecord(Base):
    __tablename__ = "ai_player_impressions"
    __table_args__ = (Index("ix_ai_player_impressions_user_category", "user_id", "category"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(240), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contradiction_batches: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_supported_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AIKnowledgeCardRecord(Base):
    __tablename__ = "ai_knowledge_cards"
    __table_args__ = (Index("ix_ai_knowledge_cards_topic_enabled_priority", "topic", "enabled", "priority"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AIImpressionCandidateRecord(Base):
    __tablename__ = "ai_impression_candidates"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "content", "conflict_entry_id"),
        Index("ix_ai_impression_candidates_user_category", "user_id", "category"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(240), nullable=False)
    support_batches: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    conflict_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_player_impressions.id")
    )
    last_supported_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AIActivityFactRecord(Base):
    __tablename__ = "ai_activity_facts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    activity_type: Mapped[str] = mapped_column(String(48), primary_key=True)
    participation_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    win_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    loss_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_result: Mapped[str] = mapped_column(String(32), nullable=False)
    last_result_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class AIActivityEventRecord(Base):
    __tablename__ = "ai_activity_events"

    event_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class DepartmentRecord(Base):
    __tablename__ = "departments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class PromotionRequestRecord(Base):
    __tablename__ = "promotion_requests"
    __table_args__ = (
        Index(
            "ux_promotion_requests_pending_employee",
            "applicant_id",
            unique=True,
            sqlite_where=text("state = 'pending'"),
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4, nullable=False)
    number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_rank_id: Mapped[UUID] = mapped_column(ForeignKey("ranks.id"), nullable=False)
    target_rank_id: Mapped[UUID] = mapped_column(ForeignKey("ranks.id"), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class PromotionApprovalRecord(Base):
    __tablename__ = "promotion_approvals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("promotion_requests.id"), unique=True, nullable=False
    )
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class DepartmentRequestRecord(Base):
    __tablename__ = "department_requests"
    __table_args__ = (
        Index(
            "ux_department_requests_pending_employee",
            "applicant_id",
            unique=True,
            sqlite_where=text("state = 'pending'"),
            postgresql_where=text("state = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, unique=True, default=uuid4, nullable=False)
    number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    applicant_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    source_department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False
    )
    target_department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    requested_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class DepartmentApprovalRecord(Base):
    __tablename__ = "department_approvals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("department_requests.id"), unique=True, nullable=False
    )
    approver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class DailyCheckinRecord(Base):
    __tablename__ = "daily_checkins"
    __table_args__ = (UniqueConstraint("user_id", "checkin_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    checked_in_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class WeeklyAttendanceSettlementRecord(Base):
    __tablename__ = "weekly_attendance_settlements"
    __table_args__ = (UniqueConstraint("user_id", "week_start"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class DailyActivityRecord(Base):
    __tablename__ = "daily_activities"
    __table_args__ = (UniqueConstraint("user_id", "activity_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    activity_date: Mapped[date] = mapped_column(Date, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ActivityRewardSettlementRecord(Base):
    __tablename__ = "activity_reward_settlements"
    __table_args__ = (UniqueConstraint("user_id", "activity_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    activity_date: Mapped[date] = mapped_column(Date, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    reward: Mapped[int] = mapped_column(Integer, nullable=False)
    settled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class BalanceTransactionRecord(Base):
    __tablename__ = "balance_transactions"
    __table_args__ = (
        Index("ix_balance_transactions_user_occurred", "user_id", "occurred_at"),
        Index(
            "ix_balance_transactions_dark_market_listing_occurred",
            "dark_market_listing_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    dark_market_listing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("dark_market_listings.id")
    )


class ItemRecord(Base):
    __tablename__ = "items"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False)
    unlimited_stock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    system_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    effect_type: Mapped[str | None] = mapped_column(String(32))
    minimum_rank_order: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class UserItemRecord(Base):
    __tablename__ = "user_items"
    __table_args__ = (UniqueConstraint("user_id", "item_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    item_id: Mapped[UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class ShopPurchaseRecord(Base):
    __tablename__ = "shop_purchases"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    item_id: Mapped[UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class ShopPurchaseDailyUsageRecord(Base):
    __tablename__ = "shop_purchase_daily_usage"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", "category"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ShopDailyBonusRecord(Base):
    __tablename__ = "shop_daily_bonuses"
    __table_args__ = (UniqueConstraint("user_id", "usage_date"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    ai_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ai_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    multiplayer_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    multiplayer_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ShopMultiplayerDailyStartRecord(Base):
    __tablename__ = "shop_multiplayer_daily_starts"
    __table_args__ = (UniqueConstraint("user_id", "play_date", "game_type"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    play_date: Mapped[date] = mapped_column(Date, nullable=False)
    game_type: Mapped[str] = mapped_column(String(32), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ShopItemUseRecord(Base):
    __tablename__ = "shop_item_uses"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    item_id: Mapped[UUID] = mapped_column(ForeignKey("items.id"), nullable=False)
    target_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class AdultCardSessionRecord(Base):
    __tablename__ = "adult_card_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    item_use_id: Mapped[UUID] = mapped_column(
        ForeignKey("shop_item_uses.id"), unique=True, nullable=False
    )
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    source_inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    scene: Mapped[str | None] = mapped_column(String(200))
    desired_participant_count: Mapped[int | None] = mapped_column(Integer)
    expected_recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    consent_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class AdultCardParticipantRecord(Base):
    __tablename__ = "adult_card_participants"
    __table_args__ = (UniqueConstraint("session_id", "user_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("adult_card_sessions.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    invitation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(16))
    authorization_outbound_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id")
    )
    decided_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class ShopSceneJobRecord(Base):
    __tablename__ = "shop_scene_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("adult_card_sessions.id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_text: Mapped[str | None] = mapped_column(Text)
    failure_summary: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class ShopCommonSenseStateRecord(Base):
    __tablename__ = "shop_common_sense_states"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("adult_card_sessions.id"), unique=True, nullable=False
    )
    target_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class ShopSessionNumberCounterRecord(Base):
    __tablename__ = "shop_session_number_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False)


class OutboundRecord(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index(
            "ix_outbound_messages_claim",
            "status",
            "lease_expires_at",
            "created_at",
            "reply_index",
            postgresql_where=text("status IN ('pending', 'leased')"),
        ),
        Index(
            "ix_outbound_messages_delivery_order",
            "delivery_key",
            "status",
            "created_at",
            "reply_index",
            "id",
        ),
        Index(
            "ux_outbound_messages_held_performance_key",
            "deferred_by_performance_id",
            "performance_defer_key",
            unique=True,
            sqlite_where=text(
                "status = 'held_performance' AND performance_defer_key IS NOT NULL"
            ),
            postgresql_where=text(
                "status = 'held_performance' AND performance_defer_key IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID
    )
    inbound_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inbound_messages.id")
    )
    destination_chatroom_id: Mapped[str | None] = mapped_column(String(255))
    delivery_key: Mapped[str] = mapped_column(
        String(255), default="__group__", server_default="__group__", nullable=False
    )
    delivery_kind: Mapped[str] = mapped_column(
        String(32), default="group", nullable=False
    )
    reference_message_id: Mapped[str | None] = mapped_column(String(255))
    reference_sender_platform_id: Mapped[str | None] = mapped_column(String(255))
    reference_content_type: Mapped[str | None] = mapped_column(String(32))
    reference_text: Mapped[str | None] = mapped_column(Text)
    reply_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(16), default="text", server_default="text", nullable=False
    )
    image_url: Mapped[str | None] = mapped_column(Text)
    image_alt: Mapped[str | None] = mapped_column(String(512))
    deferred_by_performance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("performance_reservations.id")
    )
    performance_defer_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    platform_sent_id: Mapped[str | None] = mapped_column(String(255))
    recall_after_seconds: Mapped[int | None] = mapped_column(Integer)
    recall_due_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    recall_status: Mapped[str | None] = mapped_column(String(32))
    recall_lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    recall_lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    recall_lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    recall_attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    recalled_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, onupdate=beijing_now, nullable=False
    )


class IncomeReportDeliveryRecord(Base):
    __tablename__ = "income_report_deliveries"
    __table_args__ = (
        UniqueConstraint("group_chat_id", "report_date", "report_time"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(
        ForeignKey("group_chats.id"), default=PRIMARY_GROUP_CHAT_ID, nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_time: Mapped[str] = mapped_column(String(5), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    outbound_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_messages.id"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class WorkerInstanceRecord(Base):
    __tablename__ = "worker_instances"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    worker_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    login_state: Mapped[str] = mapped_column(String(32), nullable=False)
    listening: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    listening_desired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    account_display_name: Mapped[str | None] = mapped_column(String(255))
    bot_delivery_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    bot_delivery_error: Mapped[str | None] = mapped_column(String(255))
    recorded_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    browser_state: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)


class WorkerCommandRecord(Base):
    __tablename__ = "worker_commands"
    __table_args__ = (
        Index(
            "ix_worker_commands_claim",
            "status",
            "lease_expires_at",
            "created_at",
            postgresql_where=text("status IN ('pending', 'leased')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    lease_worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class LoginSessionRecord(Base):
    __tablename__ = "login_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)


class ManualLoginLeaseRecord(Base):
    __tablename__ = "manual_login_leases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    operator_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AdminAccountRecord(Base):
    __tablename__ = "admin_accounts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AdminSessionRecord(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_accounts.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AdminIdempotencyRecord(Base):
    __tablename__ = "admin_idempotency_records"
    __table_args__ = (UniqueConstraint("actor_key", "key_hash"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_key: Mapped[str] = mapped_column(String(160), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        BeijingDateTime, default=beijing_now, nullable=False
    )


class AdminConfigRevisionRecord(Base):
    __tablename__ = "admin_config_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
