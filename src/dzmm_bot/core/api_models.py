from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from dzmm_bot.runtime.contracts import LoginState
from .schema import PRIMARY_GROUP_CHAT_ID


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageReferenceRequest(ApiModel):
    message_id: str = Field(min_length=1, max_length=255)
    sender_platform_id: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=32)
    image_url: str | None = Field(default=None, max_length=4096)
    alt: str | None = Field(default=None, max_length=512)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    blurhash: str | None = Field(default=None, max_length=512)
    text: str | None = None


class InboundRequest(ApiModel):
    platform_message_id: str = Field(min_length=1, max_length=255)
    sender_platform_id: str = Field(min_length=1, max_length=255)
    content: str
    received_at: AwareDatetime
    source_type: Literal["group", "direct"] = "group"
    chatroom_id: str | None = Field(default=None, max_length=255)
    reference: MessageReferenceRequest | None = None

    @model_validator(mode="after")
    def validate_direct_room(self):
        if self.source_type == "direct" and not self.chatroom_id:
            raise ValueError("direct inbound requires chatroom_id")
        return self


class InboundResponse(ApiModel):
    message_id: UUID
    accepted: bool


class DirectChatRoomRequest(ApiModel):
    platform_user_id: str = Field(min_length=1, max_length=255)
    chatroom_id: str = Field(min_length=1, max_length=255)


class DirectChatSyncRequest(ApiModel):
    rooms: list[DirectChatRoomRequest]
    now: AwareDatetime


class DirectInboundRoomsResponse(ApiModel):
    chatroom_ids: list[str]


class GroupChatRuntimeResponse(ApiModel):
    connection_state: Literal["pending", "connected", "failed", "disabled"]
    last_connected_at: datetime | None
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    last_error_summary: str | None
    worker_id: str | None
    updated_at: datetime


class GroupChatResponse(ApiModel):
    id: UUID
    name: str
    chat_url: str | None
    chatroom_id: str | None
    listening_enabled: bool
    games_enabled: bool
    random_events_enabled: bool
    announcements_enabled: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    runtime: GroupChatRuntimeResponse | None = None


class CreateGroupChatRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    chat_url: str = Field(min_length=1, max_length=4096)
    listening_enabled: bool = True
    games_enabled: bool = True
    random_events_enabled: bool = True
    announcements_enabled: bool = True
    now: AwareDatetime


class UpdateGroupChatRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    chat_url: str | None = Field(default=None, min_length=1, max_length=4096)
    listening_enabled: bool | None = None
    games_enabled: bool | None = None
    random_events_enabled: bool | None = None
    announcements_enabled: bool | None = None
    now: AwareDatetime


class DeleteGroupChatRequest(ApiModel):
    now: AwareDatetime


class GroupChatTargetResponse(ApiModel):
    group_chat_id: UUID
    chatroom_id: str
    chat_url: str


class GroupChatRuntimeUpdateRequest(ApiModel):
    group_chat_id: UUID
    connection_state: Literal["pending", "connected", "failed", "disabled"]
    last_connected_at: AwareDatetime | None = None
    last_inbound_at: AwareDatetime | None = None
    last_outbound_at: AwareDatetime | None = None
    last_error_summary: str | None = Field(default=None, max_length=512)


class SyncGroupChatRuntimeRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    statuses: list[GroupChatRuntimeUpdateRequest] = Field(max_length=100)
    now: AwareDatetime


class ClaimRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    now: AwareDatetime
    lease_seconds: int = Field(gt=0)
    excluded_delivery_keys: list[str] = Field(default_factory=list, max_length=16)
    required_delivery_key: str | None = Field(default=None, min_length=1, max_length=255)


class OutboundClaimResponse(ApiModel):
    id: UUID
    inbound_message_id: UUID | None
    group_chat_id: UUID | None
    text: str
    content_type: Literal["text", "image"]
    image_url: str | None
    image_alt: str | None
    lease_token: UUID
    lease_expires_at: datetime
    attempt_count: int
    destination_chatroom_id: str | None
    delivery_key: str
    delivery_kind: str
    reference_message_id: str | None
    reference_sender_platform_id: str | None
    reference_content_type: str | None
    reference_text: str | None
    recall_after_seconds: int | None


class SentRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    platform_sent_id: str = Field(min_length=1, max_length=255)
    now: AwareDatetime


class FailedRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    now: AwareDatetime


class OutboundRecallClaimResponse(ApiModel):
    id: UUID
    platform_sent_id: str
    lease_token: UUID
    lease_expires_at: datetime
    attempt_count: int


class RecalledRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    now: AwareDatetime


class AcceptedResponse(ApiModel):
    accepted: bool


class HeartbeatRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    login_state: LoginState
    recorded_at: AwareDatetime
    listening: bool = True


class HeartbeatResponse(ApiModel):
    worker_id: str
    login_state: LoginState
    recorded_at: datetime
    listening: bool
    listening_desired: bool


class HealthResponse(ApiModel):
    database_available: bool
    latest_worker_heartbeat_age_seconds: float | None


class QueueCountsResponse(ApiModel):
    inbound_accepted: int
    outbound_pending: int
    worker_commands_pending: int


class AdminStatusResponse(ApiModel):
    state: str
    last_heartbeat: datetime | None
    listening: bool | None
    listening_desired: bool | None
    queue_counts: QueueCountsResponse


class CommandTemplateResponse(ApiModel):
    scenario: str
    label: str
    template: str
    variables: list[str]


class CommandDefinitionResponse(ApiModel):
    command: str
    description: str
    enabled: bool
    templates: list[CommandTemplateResponse]


class SetCommandEnabledRequest(ApiModel):
    command: str = Field(min_length=1, max_length=32)
    enabled: bool


class SetCommandTemplateRequest(ApiModel):
    command: str = Field(min_length=1, max_length=32)
    scenario: str = Field(min_length=1, max_length=64)
    template: str = Field(min_length=1, max_length=2000)


class UserResponse(ApiModel):
    platform_id: str
    display_name: str
    employee_number: int
    balance: int
    joined_at: datetime
    rank_name: str
    rank_level_label: str
    department_name: str


class BalanceTransactionResponse(ApiModel):
    id: UUID
    amount: int
    source: str
    source_label: str
    occurred_at: datetime
    balance_after: int


class PaginatedBalanceTransactionsResponse(ApiModel):
    platform_id: str
    display_name: str
    current_balance: int
    items: list[BalanceTransactionResponse]
    page: int
    page_size: int
    total: int
    pages: int


class RankResponse(ApiModel):
    id: UUID
    sort_order: int
    name: str
    level_label: str
    promotion_price: int
    vote_weight: int
    multiplayer_game_limit: int
    has_group_management: bool
    is_board: bool
    enabled: bool


class UpdateRankRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    promotion_price: int = Field(ge=0, le=99999)
    vote_weight: int = Field(ge=0, le=99)
    multiplayer_game_limit: int = Field(ge=-1, le=999)
    has_group_management: bool
    enabled: bool


class DepartmentResponse(ApiModel):
    id: UUID
    name: str
    description: str
    is_default: bool
    enabled: bool


class CreateDepartmentRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)


class UpdateDepartmentRequest(CreateDepartmentRequest):
    enabled: bool


class PaginatedDepartmentsResponse(ApiModel):
    items: list[DepartmentResponse]
    page: int
    page_size: int
    total: int
    pages: int


class PromotionRequestResponse(ApiModel):
    number: int
    applicant_platform_id: str
    applicant_name: str
    source_rank_name: str
    target_rank_name: str
    price: int
    state: str
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None


class PaginatedPromotionRequestsResponse(ApiModel):
    items: list[PromotionRequestResponse]
    page: int
    page_size: int
    total: int
    pages: int


class DepartmentRequestResponse(ApiModel):
    number: int
    applicant_platform_id: str
    applicant_name: str
    source_department_name: str
    target_department_name: str
    state: str
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    approver_name: str | None
    decision: str | None


class PaginatedDepartmentRequestsResponse(ApiModel):
    items: list[DepartmentRequestResponse]
    page: int
    page_size: int
    total: int
    pages: int


class SetBoardMembershipRequest(ApiModel):
    member: bool


class UserProfileResponse(ApiModel):
    platform_id: str
    display_name: str
    balance: int
    rank: RankResponse
    department: DepartmentResponse


class ItemResponse(ApiModel):
    name: str
    description: str
    price: int
    stock: int
    enabled: bool


class PaginatedUsersResponse(ApiModel):
    items: list[UserResponse]
    page: int
    page_size: int
    total: int
    pages: int


class PaginatedItemsResponse(ApiModel):
    items: list[ItemResponse]
    page: int
    page_size: int
    total: int
    pages: int


class CreateItemRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1)
    price: int = Field(ge=0, le=999)
    stock: int = Field(ge=0, le=999)


class GameSettingsResponse(ApiModel):
    currency_name: str
    onboarding_bonus: int
    checkin_reward: int
    weekly_attendance_reward: int
    reset_time_label: str = "北京时间 00:00"


class SetGameSettingsRequest(ApiModel):
    currency_name: str = Field(min_length=1, max_length=12)
    onboarding_bonus: int = Field(ge=0, le=999)
    checkin_reward: int = Field(ge=0, le=999)
    weekly_attendance_reward: int = Field(ge=0, le=999)


class ProfileSettingsResponse(ApiModel):
    edit_cost: int = Field(ge=0, le=99999)
    shared_labor: int = Field(ge=0, le=99999)
    version: int = Field(ge=0)


class SetProfileSettingsRequest(ProfileSettingsResponse):
    pass


class PersonalProfileResponse(ApiModel):
    platform_id: str
    display_name: str
    profile_text: str = Field(max_length=800)
    profile_image_url: str | None
    profile_version: int = Field(ge=0)
    latest_upload: dict | None


class SetPersonalProfileRequest(ApiModel):
    profile_text: str = Field(max_length=800)


class ProfileImageUploadClaimResponse(ApiModel):
    id: UUID
    temp_path: str
    original_filename: str
    mime_type: str
    expected_profile_version: int = Field(ge=0)
    lease_token: UUID
    attempt_count: int = Field(ge=1)


class ProfileImageCleanupClaimResponse(ApiModel):
    id: UUID
    temp_path: str
    lease_token: UUID


class CompleteProfileImageUploadRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    result_url: str = Field(min_length=1, max_length=4096)
    now: AwareDatetime


class FailProfileImageUploadRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    failure_summary: str = Field(min_length=1, max_length=128)
    now: AwareDatetime


class CreateProfileImageUploadRequest(ApiModel):
    temp_path: str = Field(min_length=1, max_length=4096)
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    now: AwareDatetime


class ProfileImageUploadStatusResponse(ApiModel):
    id: UUID
    platform_id: str
    status: Literal["pending", "processing", "completed", "failed", "superseded"]
    result_url: str | None
    failure_summary: str | None
    expected_profile_version: int = Field(ge=0)


class AIRankQuotaResponse(ApiModel):
    rank_id: UUID
    rank_name: str
    rank_level_label: str
    daily_limit: int = Field(ge=0, le=100)


class SetAIRankQuotaRequest(ApiModel):
    rank_id: UUID
    daily_limit: int = Field(ge=0, le=100)


class AIAssistantSettingsResponse(ApiModel):
    enabled: bool
    persona: str
    system_prompt: str
    over_limit_reply: str
    failure_reply: str
    max_response_chars: int = Field(ge=1, le=10000)
    timeout_seconds: int = Field(ge=1, le=60)
    quotas: list[AIRankQuotaResponse]
    memory_enabled: bool
    extraction_prompt: str
    history_limit: int = Field(ge=1, le=500)
    max_memory_chars: int = Field(ge=1, le=8000)
    batch_message_threshold: int = Field(ge=1, le=500)
    max_entries_per_category: int = Field(ge=1, le=10)
    candidate_expiry_days: int = Field(ge=1, le=365)


class SetAIAssistantSettingsRequest(ApiModel):
    enabled: bool
    persona: str = Field(min_length=1, max_length=99999)
    system_prompt: str = Field(min_length=1, max_length=99999)
    over_limit_reply: str = Field(min_length=1, max_length=1000)
    failure_reply: str = Field(min_length=1, max_length=1000)
    max_response_chars: int = Field(ge=1, le=10000)
    timeout_seconds: int = Field(ge=1, le=60)
    quotas: list[SetAIRankQuotaRequest] = Field(min_length=1, max_length=100)
    memory_enabled: bool
    extraction_prompt: str = Field(min_length=1, max_length=99999)
    history_limit: int = Field(ge=1, le=500)
    max_memory_chars: int = Field(ge=1, le=8000)
    batch_message_threshold: int = Field(ge=1, le=500)
    max_entries_per_category: int = Field(ge=1, le=10)
    candidate_expiry_days: int = Field(ge=1, le=365)


AIImpressionCategory = Literal[
    "expression_style",
    "group_interaction",
    "humor_style",
    "interests",
    "supervisor_interaction",
    "boundaries",
]

AIKnowledgeTopic = Literal[
    "economy", "departments", "ranks", "shop", "checkin_activity",
    "random_events", "hide_and_seek", "memory_assessment", "undercover",
    "blame_bomb", "number_bomb", "commands_help", "player_activity",
]


class AIKnowledgeCardResponse(ApiModel):
    id: UUID
    topic: AIKnowledgeTopic
    title: str
    keywords: list[str]
    content: str
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime


class SetAIKnowledgeCardRequest(ApiModel):
    topic: AIKnowledgeTopic
    title: str = Field(min_length=1, max_length=128)
    keywords: list[str] = Field(min_length=1, max_length=30)
    content: str = Field(min_length=1, max_length=12000)
    enabled: bool
    priority: int = Field(ge=0, le=10000)


class AIPlayerImpressionResponse(ApiModel):
    id: UUID
    category: AIImpressionCategory
    content: str
    source: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


class AIActivityFactResponse(ApiModel):
    activity_type: str
    participation_count: int
    win_count: int
    loss_count: int
    last_result: str
    last_result_at: datetime


class AIPlayerMemoryResponse(ApiModel):
    platform_id: str
    display_name: str
    impressions: list[AIPlayerImpressionResponse]
    activity_facts: list[AIActivityFactResponse]
    legacy_memory_text: str
    updated_at: datetime | None


class CreateAIPlayerImpressionRequest(ApiModel):
    category: AIImpressionCategory
    content: str = Field(min_length=1, max_length=240)


class UpdateAIPlayerImpressionRequest(ApiModel):
    category: AIImpressionCategory
    content: str = Field(min_length=1, max_length=240)
    pinned: bool


class AIConversationMessageResponse(ApiModel):
    role: Literal["user", "assistant"]
    content: str


class AIClaimResponse(ApiModel):
    id: UUID
    lease_token: UUID
    system_prompt: str
    history_messages: list[AIConversationMessageResponse]
    user_content: str
    max_response_chars: int = Field(ge=1, le=10000)
    timeout_seconds: int = Field(ge=1, le=60)


class AICompleteRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    text: str = Field(min_length=1, max_length=10000)
    now: AwareDatetime


class AIFailedRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    failure_summary: Literal["timeout", "network", "http_error", "invalid_response"]
    now: AwareDatetime


class AIImpressionOperationModel(ApiModel):
    action: Literal[
        "new_candidate",
        "reinforce_candidate",
        "weaken_entry",
        "replace_entry",
        "keep",
    ]
    category: AIImpressionCategory | None = None
    content: str | None = Field(default=None, max_length=240)
    candidate_id: UUID | None = None
    entry_id: UUID | None = None

    @model_validator(mode="after")
    def validate_action_fields(self):
        present = {
            name
            for name in ("category", "content", "candidate_id", "entry_id")
            if getattr(self, name) is not None
        }
        expected = {
            "new_candidate": {"category", "content"},
            "reinforce_candidate": {"candidate_id"},
            "weaken_entry": {"entry_id"},
            "replace_entry": {"entry_id", "category", "content"},
            "keep": set(),
        }[self.action]
        if present != expected or (
            self.content is not None and not self.content.strip()
        ):
            raise ValueError("印象操作字段无效")
        return self


class AIImpressionEntryResponse(ApiModel):
    id: UUID
    category: AIImpressionCategory
    content: str
    pinned: bool


class AIImpressionCandidateResponse(ApiModel):
    id: UUID
    category: AIImpressionCategory
    content: str
    support_batches: int = Field(ge=1)
    conflict_entry_id: UUID | None


class AIMemoryClaimResponse(ApiModel):
    user_id: UUID
    target_message_id: UUID
    lease_token: UUID
    extraction_prompt: str
    max_memory_chars: int = Field(ge=1, le=8000)
    stable_entries: list[AIImpressionEntryResponse]
    candidates: list[AIImpressionCandidateResponse]
    source_messages: list[str]
    source_message_count: int = Field(ge=0, le=500)


class AIMemoryCompleteRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    target_message_id: UUID
    operations: list[AIImpressionOperationModel] = Field(max_length=50)
    source_message_count: int = Field(ge=0, le=500)
    now: AwareDatetime


class AIMemoryFailedRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    failure_summary: Literal["timeout", "network", "http_error", "invalid_response"]
    now: AwareDatetime


class ActivityLevelRuleModel(ApiModel):
    level: int = Field(ge=1, le=10)
    character_threshold: int = Field(ge=0)
    reward: int = Field(ge=0, le=999)


class ActivitySettingsResponse(ApiModel):
    rules: list[ActivityLevelRuleModel]
    report_times: list[str]


class SetActivitySettingsRequest(ApiModel):
    rules: list[ActivityLevelRuleModel] = Field(min_length=10, max_length=10)
    report_times: list[str] = Field(min_length=1)


class NumberBombSettingsResponse(ApiModel):
    enabled: bool
    signup_timeout_minutes: int
    reminder_interval_seconds: int


class SetNumberBombSettingsRequest(ApiModel):
    enabled: bool
    signup_timeout_minutes: int = Field(ge=1, le=60)
    reminder_interval_seconds: int = Field(ge=5, le=300)


class RedPacketSettingsResponse(ApiModel):
    expiry_minutes: int
    empty_probability_percent: int


class SetRedPacketSettingsRequest(ApiModel):
    expiry_minutes: int = Field(ge=1, le=60)
    empty_probability_percent: int = Field(ge=0, le=30)


class GameplayParticipantResponse(ApiModel):
    number: int | None = None
    display_name: str
    reported: bool | None = None


class GameplaySummaryResponse(ApiModel):
    group_chat_id: UUID
    group_name: str
    game_type: str | None = None
    game_id: UUID | None = None
    state: str | None = None
    participants: list[GameplayParticipantResponse] = Field(default_factory=list)
    signup_deadline: AwareDatetime | None = None
    next_reminder_at: AwareDatetime | None = None
    tipping_deadline: AwareDatetime | None = None
    tip_total: int = 0
    skip_enabled: bool = False


class GameplaySummariesResponse(ApiModel):
    items: list[GameplaySummaryResponse] = Field(default_factory=list)


class RandomEventSettingsResponse(ApiModel):
    schedule_times: list[str] = Field(min_length=1, max_length=24)
    signup_notice_template: str = Field(min_length=1, max_length=2000)
    signup_timeout_minutes: int
    reminder_interval_minutes: int
    signup_allowed_commands: list[str] = Field(max_length=32)
    in_progress_allowed_commands: list[str] = Field(max_length=32)
    blocked_message: str = Field(min_length=1, max_length=2000)
    submission_enabled: bool = True
    submission_draft_timeout_minutes: int = Field(default=30, ge=1, le=1440)
    submission_max_participants: int = Field(default=99, ge=1, le=999)
    submission_default_target_rounds: int = Field(default=10, ge=1, le=999)
    submission_default_event_reward: int = Field(default=6, ge=0, le=999)
    submission_approval_reward: int = Field(default=10, ge=0, le=999)
    tipping_duration_seconds: int = Field(default=120, ge=10, le=3600)


class SetRandomEventSettingsRequest(RandomEventSettingsResponse):
    submission_enabled: bool | None = None
    submission_draft_timeout_minutes: int | None = Field(default=None, ge=1, le=1440)
    submission_max_participants: int | None = Field(default=None, ge=1, le=999)
    submission_default_target_rounds: int | None = Field(default=None, ge=1, le=999)
    submission_default_event_reward: int | None = Field(default=None, ge=0, le=999)
    submission_approval_reward: int | None = Field(default=None, ge=0, le=999)
    tipping_duration_seconds: int | None = Field(default=None, ge=10, le=3600)


class HideAndSeekSettingsResponse(ApiModel):
    enabled: bool
    entry_fee: int = Field(ge=0, le=999)
    win_reward: int = Field(ge=0, le=999)
    daily_limit: int = Field(ge=1, le=99)
    selection_timeout_minutes: int = Field(ge=1, le=60)


class SetHideAndSeekSettingsRequest(HideAndSeekSettingsResponse):
    pass


class MemoryAssessmentLevelRuleModel(ApiModel):
    level: int = Field(ge=1, le=20)
    answer_length: int = Field(ge=1, le=200)
    reward: int = Field(ge=1, le=999)


class MemoryAssessmentSettingsResponse(ApiModel):
    enabled: bool
    single_daily_limit: int = Field(ge=1, le=99)
    single_recall_seconds: int = Field(ge=1, le=60)
    duel_recall_seconds: int = Field(ge=1, le=60)
    duel_difficulty_level: int = Field(ge=1, le=20)
    duel_base_pool: int = Field(ge=1, le=999)
    duel_wrong_freeze: int = Field(ge=1, le=999)
    duel_wrong_limit: int = Field(ge=1, le=99)
    duel_answer_timeout_minutes: int = Field(ge=1, le=60)
    duel_signup_timeout_minutes: int = Field(default=2, ge=1, le=60)
    character_set: str = Field(min_length=2, max_length=200)
    levels: list[MemoryAssessmentLevelRuleModel] = Field(min_length=1, max_length=20)


class SetMemoryAssessmentSettingsRequest(MemoryAssessmentSettingsResponse):
    pass


class UndercoverRoleRuleModel(ApiModel):
    player_count: int = Field(ge=4, le=8)
    civilian_count: int = Field(ge=0, le=8)
    undercover_count: int = Field(ge=0, le=8)
    whiteboard_count: int = Field(ge=0, le=8)


class UndercoverSettingsResponse(ApiModel):
    enabled: bool
    vote_seconds: int = Field(ge=1, le=3600)
    whiteboard_win_remaining: int = Field(ge=2, le=8)
    signup_timeout_minutes: int = Field(default=2, ge=1, le=60)
    roles: list[UndercoverRoleRuleModel] = Field(min_length=5, max_length=5)


class SetUndercoverSettingsRequest(UndercoverSettingsResponse):
    pass


class UndercoverSessionResponse(ApiModel):
    state: str | None
    target_player_count: int
    player_count: int
    queued_count: int
    current_vote_round: int
    vote_deadline: datetime | None


class BlameGameDurationRuleModel(ApiModel):
    player_count: int = Field(ge=2, le=10)
    minimum_seconds: int = Field(ge=1, le=3600)
    maximum_seconds: int = Field(ge=1, le=3600)


class BlameGameSettingsResponse(ApiModel):
    enabled: bool
    signup_timeout_seconds: int = Field(ge=1, le=3600)
    turn_timeout_seconds: int = Field(ge=1, le=3600)
    durations: list[BlameGameDurationRuleModel] = Field(min_length=9, max_length=9)


class SetBlameGameSettingsRequest(BlameGameSettingsResponse):
    pass


class BlameIncidentCardResponse(ApiModel):
    id: UUID
    name: str
    description: str
    keywords: list[str]
    enabled: bool


class PaginatedBlameIncidentCardsResponse(ApiModel):
    items: list[BlameIncidentCardResponse]
    page: int
    page_size: int
    total: int
    pages: int


class CreateBlameIncidentCardRequest(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2000)
    keywords: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        min_length=1, max_length=4
    )


class UpdateBlameIncidentCardRequest(CreateBlameIncidentCardRequest):
    enabled: bool


class BlameGamePlayerResponse(ApiModel):
    display_name: str
    seat_number: int | None
    state: str


class BlameGameIncidentResponse(ApiModel):
    name: str
    description: str
    keywords: list[str]


class BlameGameHolderResponse(ApiModel):
    display_name: str
    seat_number: int


class BlameGameSessionResponse(ApiModel):
    state: str | None
    target_player_count: int
    players: list[BlameGamePlayerResponse]
    incident: BlameGameIncidentResponse | None
    current_holder: BlameGameHolderResponse | None
    temperature: str | None


class HideAndSeekSceneResponse(ApiModel):
    id: UUID
    name: str
    enabled: bool


class PaginatedHideAndSeekScenesResponse(ApiModel):
    items: list[HideAndSeekSceneResponse]
    page: int
    page_size: int
    total: int
    pages: int


class CreateHideAndSeekSceneRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)


class UpdateHideAndSeekSceneRequest(CreateHideAndSeekSceneRequest):
    enabled: bool


class RandomEventSeatModel(ApiModel):
    role: str = Field(min_length=1, max_length=32)
    capacity: int = Field(ge=1, le=99)


class RandomEventTemplateModel(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    opening_text: str = Field(min_length=1, max_length=2000)


class RandomEventSceneResponse(ApiModel):
    id: UUID
    name: str
    signup_text: str
    openings: list[str]
    events: list[RandomEventTemplateModel]
    reward: int
    target_rounds: int
    enabled: bool
    seats: list[RandomEventSeatModel]


class PaginatedRandomEventScenesResponse(ApiModel):
    items: list[RandomEventSceneResponse]
    page: int
    page_size: int
    total: int
    pages: int


class CreateRandomEventSceneRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    signup_text: str = Field(min_length=1, max_length=2000)
    openings: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=20)
    events: list[RandomEventTemplateModel] = Field(default_factory=list, max_length=20)
    reward: int = Field(ge=0, le=999)
    target_rounds: int = Field(ge=1, le=999)
    seats: list[RandomEventSeatModel] = Field(min_length=1, max_length=20)


class UpdateRandomEventSceneRequest(CreateRandomEventSceneRequest):
    enabled: bool


class RandomEventScheduleResponse(ApiModel):
    id: UUID
    group_chat_id: UUID
    event_date: date
    scheduled_at: datetime
    status: str
    scene_name: str | None
    event_name: str | None
    is_cross_day: bool


class CreateTodayRandomEventRequest(ApiModel):
    group_chat_id: UUID = PRIMARY_GROUP_CHAT_ID
    scene_id: UUID
    event_name: str = Field(min_length=1, max_length=64)
    scheduled_at: datetime


class RandomEventDetailResponse(ApiModel):
    display_name: str
    content: str
    occurred_at: datetime


class RandomEventTipDetailResponse(ApiModel):
    sender_display_name: str
    recipient_display_name: str
    amount: int
    created_at: datetime


class RandomEventDetailsResponse(ApiModel):
    items: list[RandomEventDetailResponse]
    tips: list[RandomEventTipDetailResponse] = Field(default_factory=list)


class RescheduleRandomEventRequest(ApiModel):
    scheduled_at: AwareDatetime


class DailyJobsRequest(ApiModel):
    now: AwareDatetime


class ManualLoginActorRequest(ApiModel):
    operator_id: str = Field(min_length=1, max_length=64)
    operator_name: str = Field(min_length=1, max_length=32)


class ManualLoginLeaseResponse(ApiModel):
    operator_id: str
    operator_name: str
    expires_at: datetime


WorkerCommandKind = Literal[
    "pause_listening",
    "resume_listening",
    "restart_browser",
    "start_auth",
    "finish_auth",
    "cancel_auth",
    "retract_test",
]


class WorkerCommandRequest(ApiModel):
    command: WorkerCommandKind


class WorkerCommandResponse(ApiModel):
    id: UUID
    command: WorkerCommandKind
    status: str
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None


class CompleteWorkerCommandRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    status: Literal["completed", "failed"]
    now: AwareDatetime
