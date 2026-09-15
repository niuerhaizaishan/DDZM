from datetime import date, datetime
from typing import Any, Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from dzmm_bot.runtime.contracts import LoginState
from .ai_knowledge import KNOWLEDGE_TOPICS
from .group_games import GROUP_GAME_TYPES, GroupGameType
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
    content_type: Literal["text", "image"] = "text"
    image_url: str | None = Field(default=None, max_length=4096)
    image_alt: str | None = Field(default=None, max_length=512)
    image_width: int | None = Field(default=None, ge=1)
    image_height: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_direct_room(self):
        if self.source_type == "direct" and not self.chatroom_id:
            raise ValueError("direct inbound requires chatroom_id")
        if self.content_type == "image" and not self.image_url:
            raise ValueError("image inbound requires image_url")
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
    enabled_game_types: list[GroupGameType]
    random_events_enabled: bool
    announcements_enabled: bool
    adult_shop_enabled: bool
    performances_enabled: bool
    lottery_enabled: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    runtime: GroupChatRuntimeResponse | None = None


class CreateGroupChatRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    chat_url: str = Field(min_length=1, max_length=4096)
    listening_enabled: bool = True
    games_enabled: bool = True
    enabled_game_types: list[GroupGameType] = Field(
        default_factory=lambda: list(GROUP_GAME_TYPES)
    )
    random_events_enabled: bool = True
    announcements_enabled: bool = True
    adult_shop_enabled: bool = False
    performances_enabled: bool = False
    lottery_enabled: bool = True
    now: AwareDatetime


class UpdateGroupChatRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    chat_url: str | None = Field(default=None, min_length=1, max_length=4096)
    listening_enabled: bool | None = None
    games_enabled: bool | None = None
    enabled_game_types: list[GroupGameType] | None = None
    random_events_enabled: bool | None = None
    announcements_enabled: bool | None = None
    adult_shop_enabled: bool | None = None
    performances_enabled: bool | None = None
    lottery_enabled: bool | None = None
    now: AwareDatetime


class DeleteGroupChatRequest(ApiModel):
    now: AwareDatetime


class PerformanceSettingsResponse(ApiModel):
    maximum_duration_minutes: int
    version: int


class UpdatePerformanceSettingsRequest(ApiModel):
    maximum_duration_minutes: int = Field(ge=1, le=10080)


class ReviewPerformanceRequest(ApiModel):
    actor: str = Field(min_length=1, max_length=255)
    now: AwareDatetime
    reason: str | None = Field(default=None, max_length=500)


class ReviewPerformanceExtensionRequest(ApiModel):
    actor: str = Field(min_length=1, max_length=255)
    now: AwareDatetime
    reason: str | None = Field(default=None, max_length=500)
    allow_post_preview: bool = False


class PerformanceExtensionResponse(ApiModel):
    id: UUID
    reservation_id: UUID
    duration_minutes: int
    original_scheduled_at: datetime
    proposed_scheduled_at: datetime
    state: str
    rejection_reason: str | None
    requested_at: datetime
    reviewed_at: datetime | None


class PerformanceTipResponse(ApiModel):
    sender_display_name: str
    recipient_display_name: str
    amount: int
    created_at: datetime


class PerformanceAuditResponse(ApiModel):
    event_type: str
    actor: str | None
    payload: dict[str, Any]
    created_at: datetime


class PerformanceResponse(ApiModel):
    id: UUID
    owner_platform_id: str
    owner_display_name: str
    group_chat_id: UUID
    title: str
    introduction: str
    scheduled_at: datetime
    event_date: date
    participant_names: list[str]
    cover_url: str | None
    cover_alt: str | None
    state: str
    pre_notice_sent_at: datetime | None
    tipping_deadline: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    cancellation_reason: str | None
    cancelled_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    tips: list[PerformanceTipResponse]
    audit_events: list[PerformanceAuditResponse]
    extension: PerformanceExtensionResponse | None


class PerformanceMessageResponse(ApiModel):
    id: UUID
    display_name: str
    employee_number: int
    content: str
    content_type: Literal["text", "image"]
    image_url: str | None
    image_alt: str | None
    image_width: int | None
    image_height: int | None
    created_at: datetime


class PaginatedPerformanceMessagesResponse(ApiModel):
    reservation_id: UUID
    title: str
    started_at: datetime | None
    ended_at: datetime | None
    items: list[PerformanceMessageResponse]
    page: int
    page_size: int
    total: int
    pages: int


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
    content_type: Literal["text", "image", "novel"]
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
    is_dark_market_list: bool
    dark_market_list_query_sender_name: str | None


class SentRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    platform_sent_id: str = Field(min_length=1, max_length=255)
    now: AwareDatetime


class FailedRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    now: AwareDatetime


class RetryRequest(FailedRequest):
    retry_delay_seconds: int = Field(default=5, ge=0, le=300)


class OutboundRecallClaimResponse(ApiModel):
    id: UUID
    platform_sent_id: str
    lease_token: UUID
    lease_expires_at: datetime
    attempt_count: int
    destination_chatroom_id: str | None = None


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
    account_display_name: str | None = Field(default=None, min_length=1, max_length=255)
    bot_delivery_state: Literal[
        "unconfigured", "unknown", "ready", "captcha_required"
    ] = "unknown"
    bot_delivery_error: str | None = Field(default=None, max_length=255)


class HeartbeatResponse(ApiModel):
    worker_id: str
    login_state: LoginState
    recorded_at: datetime
    listening: bool
    listening_desired: bool
    bot_delivery_state: str
    bot_delivery_error: str | None


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
    bot_delivery_state: str
    bot_delivery_error: str | None
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
    platform_nickname: str | None
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


class EmployeeGroupMessageResponse(ApiModel):
    id: UUID
    group_chat_id: UUID
    group_name: str
    content: str
    received_at: datetime


class PaginatedEmployeeGroupMessagesResponse(ApiModel):
    platform_id: str
    display_name: str
    items: list[EmployeeGroupMessageResponse]
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
    checkin_reward: int
    vote_weight: int
    multiplayer_game_limit: int
    has_group_management: bool
    is_board: bool
    enabled: bool


class UpdateRankRequest(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    promotion_price: int = Field(ge=0, le=99999)
    checkin_reward: int = Field(ge=0, le=999)
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
    public_number: int
    name: str
    description: str
    price: int
    stock: int
    unlimited_stock: bool
    system_key: str | None
    effect_type: str | None
    minimum_rank_order: int | None
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
    description: str = Field(min_length=1, max_length=200)
    price: int = Field(ge=0, le=999)
    stock: int = Field(ge=0, le=999)


class UpdateItemRequest(ApiModel):
    description: str = Field(min_length=1, max_length=200)
    enabled: bool
    minimum_rank_order: int | None = Field(default=None, ge=1, le=999)
    unlimited_stock: bool
    stock: int = Field(ge=0, le=99999)


class ShopPurchaseLogResponse(ApiModel):
    id: UUID
    created_at: datetime
    user_name: str
    item_number: int
    item_name: str
    group_name: str
    price: int


class ShopUseLogResponse(ApiModel):
    id: UUID
    created_at: datetime
    completed_at: datetime | None
    user_name: str
    target_name: str | None
    item_number: int
    item_name: str
    group_name: str
    state: str
    result: dict | None


class ShopConsentLogResponse(ApiModel):
    id: UUID
    session_number: int
    participant_name: str
    decision: str | None
    decided_at: datetime | None


class ShopSceneJobAdminResponse(ApiModel):
    id: UUID
    session_number: int
    item_name: str
    owner_name: str
    group_name: str
    status: str
    attempt_count: int
    failure_summary: str | None
    created_at: datetime
    completed_at: datetime | None


class ShopCommonStateAdminResponse(ApiModel):
    id: UUID
    session_number: int
    owner_name: str
    target_name: str
    group_name: str
    content: str
    state: str
    starts_at: datetime
    ends_at: datetime
    finished_at: datetime | None


class ShopAdminActivityResponse(ApiModel):
    purchases: list[ShopPurchaseLogResponse]
    uses: list[ShopUseLogResponse]
    consents: list[ShopConsentLogResponse]
    scene_jobs: list[ShopSceneJobAdminResponse]
    common_states: list[ShopCommonStateAdminResponse]


class GameSettingsResponse(ApiModel):
    currency_name: str
    onboarding_bonus: int
    checkin_reward: int
    weekly_attendance_reward: int
    company_story_novel_url: str | None
    reset_time_label: str = "北京时间 00:00"


class SetGameSettingsRequest(ApiModel):
    currency_name: str = Field(min_length=1, max_length=12)
    onboarding_bonus: int = Field(ge=0, le=999)
    checkin_reward: int = Field(ge=0, le=999)
    weekly_attendance_reward: int = Field(ge=0, le=999)
    company_story_novel_url: str | None = Field(default=None, max_length=4096)


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


class PlatformNicknameRefreshClaimRequest(ApiModel):
    now: AwareDatetime


class PlatformNicknameRefreshClaimResponse(ApiModel):
    platform_id: str
    chatroom_id: str


class PlatformNicknameRefreshQueueResponse(ApiModel):
    queued: int = Field(ge=0)


class CompletePlatformNicknameRefreshRequest(ApiModel):
    nickname: str | None = Field(default=None, max_length=64)
    now: AwareDatetime


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
    trigger_prefixes: list[str] = Field(min_length=1, max_length=20)
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
    trigger_prefixes: list[str] = Field(min_length=1, max_length=20)
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

AIKnowledgeTopic = Literal[*KNOWLEDGE_TOPICS]


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


class ShopSceneClaimResponse(ApiModel):
    id: UUID
    lease_token: UUID
    system_prompt: str
    user_content: str
    max_response_chars: int = Field(ge=1, le=800)
    timeout_seconds: int = Field(ge=1, le=180)


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


class NeverHaveIEverSettingsResponse(ApiModel):
    enabled: bool
    signup_timeout_minutes: int
    statement_timeout_seconds: int
    response_timeout_seconds: int


class SetNeverHaveIEverSettingsRequest(ApiModel):
    enabled: bool
    signup_timeout_minutes: int = Field(ge=1, le=60)
    statement_timeout_seconds: int = Field(ge=1, le=600)
    response_timeout_seconds: int = Field(ge=1, le=600)


class KingGameSettingsResponse(ApiModel):
    enabled: bool
    king_phase_timeout_seconds: int


class SetKingGameSettingsRequest(ApiModel):
    enabled: bool
    king_phase_timeout_seconds: int = Field(ge=1, le=3600)


class TexasHoldemSettingsResponse(ApiModel):
    enabled: bool
    minimum_players: int
    maximum_players: int
    minimum_buy_in: int
    maximum_buy_in: int
    daily_start_limit: int
    signup_timeout_seconds: int
    action_timeout_seconds: int
    small_blind_percent: int
    big_blind_percent: int


class SetTexasHoldemSettingsRequest(ApiModel):
    enabled: bool
    minimum_players: int = Field(ge=2, le=9)
    maximum_players: int = Field(ge=2, le=9)
    minimum_buy_in: int = Field(ge=1, le=99999)
    maximum_buy_in: int = Field(ge=1, le=99999)
    daily_start_limit: int = Field(ge=1, le=100)
    signup_timeout_seconds: int = Field(ge=10, le=3600)
    action_timeout_seconds: int = Field(ge=10, le=3600)
    small_blind_percent: int = Field(ge=1, le=99)
    big_blind_percent: int = Field(ge=2, le=100)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.minimum_players > self.maximum_players:
            raise ValueError("minimum_players must not exceed maximum_players")
        if self.minimum_buy_in > self.maximum_buy_in:
            raise ValueError("minimum_buy_in must not exceed maximum_buy_in")
        if self.small_blind_percent >= self.big_blind_percent:
            raise ValueError("small blind must be below big blind")
        return self


class DarkMarketRankLimitResponse(ApiModel):
    rank_id: UUID
    rank_name: str
    level_label: str
    daily_limit: int = Field(ge=-1)


class DarkMarketRankLimitRequest(ApiModel):
    rank_id: UUID
    daily_limit: int = Field(ge=-1)


class DarkMarketSettingsResponse(ApiModel):
    enabled: bool
    announcement_group_id: UUID | None
    duration_hours: int
    fee_percent: int
    disclosure_duration_value: int
    disclosure_duration_unit: Literal["minute", "hour", "day"]
    version: int
    rank_limits: list[DarkMarketRankLimitResponse]


class SetDarkMarketSettingsRequest(ApiModel):
    enabled: bool
    announcement_group_id: UUID | None
    duration_hours: int = Field(ge=1, le=24)
    fee_percent: int = Field(ge=1, le=100)
    disclosure_duration_value: int = Field(ge=1)
    disclosure_duration_unit: Literal["minute", "hour", "day"]
    rank_limits: list[DarkMarketRankLimitRequest] = Field(min_length=1)
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_rank_limits(self):
        rank_ids = [item.rank_id for item in self.rank_limits]
        if len(rank_ids) != len(set(rank_ids)):
            raise ValueError("rank limits must be unique")
        unit_minutes = {"minute": 1, "hour": 60, "day": 24 * 60}
        if (
            self.disclosure_duration_value
            * unit_minutes[self.disclosure_duration_unit]
            > 30 * 24 * 60
        ):
            raise ValueError("disclosure duration must not exceed 30 days")
        return self


class ReviewDarkMarketComplaintRequest(ApiModel):
    actor: str = Field(min_length=1, max_length=100)
    now: AwareDatetime


class CompanyLotterySettingsResponse(ApiModel):
    enabled: bool
    red_pool: int
    red_count: int
    blue_pool: int
    ticket_price: int
    head_prize: int
    second_prize: int
    third_prize: int
    fourth_prize: int
    fifth_prize: int
    pool_ceiling: int
    pool_seed: int
    per_person_cap: int
    max_tickets_per_day: int
    max_tickets_per_round: int
    draw_hour: int
    draw_minute: int
    close_offset_minutes: int
    notify_offset_minutes: int
    draft_timeout_minutes: int
    welfare_enabled: bool
    welfare_per_person: int
    welfare_min_tenure_hours: int
    combinations: int


class SetCompanyLotterySettingsRequest(ApiModel):
    enabled: bool
    red_pool: int = Field(ge=5, le=99)
    red_count: int = Field(ge=1, le=10)
    blue_pool: int = Field(ge=1, le=99)
    ticket_price: int = Field(ge=1, le=1000)
    head_prize: int = Field(ge=0, le=1_000_000)
    second_prize: int = Field(ge=0, le=1_000_000)
    third_prize: int = Field(ge=0, le=1_000_000)
    fourth_prize: int = Field(ge=0, le=1_000_000)
    fifth_prize: int = Field(ge=0, le=1_000_000)
    pool_ceiling: int = Field(ge=0, le=1_000_000)
    pool_seed: int = Field(ge=0, le=1_000_000)
    per_person_cap: int = Field(ge=0, le=1_000_000)
    max_tickets_per_day: int = Field(ge=1, le=1000)
    max_tickets_per_round: int = Field(ge=1, le=100_000)
    draw_hour: int = Field(ge=0, le=23)
    draw_minute: int = Field(ge=0, le=59)
    close_offset_minutes: int = Field(ge=1, le=720)
    notify_offset_minutes: int = Field(ge=1, le=720)
    draft_timeout_minutes: int = Field(ge=1, le=240)
    welfare_enabled: bool
    welfare_per_person: int = Field(ge=0, le=1000)
    welfare_min_tenure_hours: int = Field(ge=0, le=8760)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.red_count > self.red_pool:
            raise ValueError("红球选球数不能超过红球池")
        if self.notify_offset_minutes >= self.close_offset_minutes:
            raise ValueError("停售提醒必须早于停售")
        if self.draw_hour * 60 + self.draw_minute < self.close_offset_minutes:
            raise ValueError("开奖时刻太早，无法在当天完成停售")
        return self


class CompanyLotteryRoundSummaryResponse(ApiModel):
    round_number: int
    state: str
    open_at: AwareDatetime
    close_at: AwareDatetime
    draw_at: AwareDatetime
    drawn_at: AwareDatetime | None
    tickets_sold: int
    gross_amount: int
    winner_count: int
    payable: int
    paid_total: int
    pool_opening: int
    pool_overflow: int
    pool_closing: int
    answer: str | None
    salt: str | None


class CompanyLotteryLedgerEntryResponse(ApiModel):
    created_at: AwareDatetime
    account: str
    kind: str
    amount: int
    balance_after: int
    round_number: int | None
    note: str | None


class CompanyLotteryPrizeResponse(ApiModel):
    round_number: int
    display_name: str
    ticket: str
    tier: str
    merited_amount: int
    prize_amount: int
    settled_at: AwareDatetime | None


class CompanyLotteryEmployeeTotalResponse(ApiModel):
    display_name: str
    tickets: int
    cost: int
    prize: int
    net: int


class CompanyLotteryReconcileResponse(ApiModel):
    injected_total: int
    sales_total: int
    prize_paid_total: int
    welfare_paid_total: int
    credited_total: int
    credited_ledger_total: int
    pool_balance: int
    adjustment_balance: int
    expected_balance: int
    actual_balance: int
    balanced: bool


class CompanyLotteryOverviewResponse(ApiModel):
    enabled: bool
    pool_balance: int
    adjustment_balance: int
    employee_count: int
    current_round_number: int | None
    rounds: list[CompanyLotteryRoundSummaryResponse]
    ledger: list[CompanyLotteryLedgerEntryResponse]
    prizes: list[CompanyLotteryPrizeResponse]
    employees: list[CompanyLotteryEmployeeTotalResponse]
    reconcile: CompanyLotteryReconcileResponse


class DrawCompanyLotteryRoundRequest(ApiModel):
    actor: str = Field(min_length=1, max_length=100)
    now: AwareDatetime


class DepositCompanyLotteryPoolRequest(ApiModel):
    actor: str = Field(min_length=1, max_length=100)
    now: AwareDatetime
    account: Literal["pool", "adjustment"] = "pool"
    amount: int = Field(ge=1, le=1_000_000)


class CompanyLotteryPoolBalancesResponse(ApiModel):
    pool_balance: int
    adjustment_balance: int


class CompanyLotteryDrawResponse(ApiModel):
    round_number: int
    answer: str
    winner_count: int
    paid_total: int
    pool_balance: int
    adjustment_balance: int
    next_round_number: int


class DarkMarketBidResponse(ApiModel):
    id: UUID
    bidder_platform_id: str
    bidder_display_name: str
    amount: int
    state: str
    created_at: AwareDatetime
    refunded_at: AwareDatetime | None
    settled_at: AwareDatetime | None


class DarkMarketBalanceTransactionResponse(ApiModel):
    id: UUID
    platform_id: str
    display_name: str
    employee_number: int
    amount: int
    source: str
    source_label: str
    occurred_at: AwareDatetime


class DarkMarketListingResponse(ApiModel):
    id: UUID
    public_number: int
    seller_platform_id: str
    seller_display_name: str
    seller_employee_number: int
    buyer_platform_id: str | None
    buyer_display_name: str | None
    buyer_employee_number: int | None
    current_bidder_platform_id: str | None
    current_bidder_display_name: str | None
    name: str
    purpose: str
    details: str
    gender: str
    starting_price: int
    duration_hours_snapshot: int
    fee_percent_snapshot: int
    state: str
    ends_at: AwareDatetime
    final_amount: int | None
    fee_amount: int | None
    receipt_started_at: AwareDatetime | None
    receipt_deadline: AwareDatetime | None
    receipt_resolved_at: AwareDatetime | None
    complaint_requested_at: AwareDatetime | None
    complaint_reviewed_at: AwareDatetime | None
    complaint_reviewed_by: str | None
    complaint_decision: str | None
    complaint_refund_amount: int | None = None
    complaint_penalty_amount: int | None = None
    created_at: AwareDatetime
    finished_at: AwareDatetime | None
    disclosure_state: str | None
    disclosure_deadline: AwareDatetime | None
    seller_choice: bool | None
    buyer_choice: bool | None
    bids: list[DarkMarketBidResponse] = Field(default_factory=list)
    balance_transactions: list[DarkMarketBalanceTransactionResponse] = Field(
        default_factory=list
    )


class PaginatedDarkMarketListingsResponse(ApiModel):
    items: list[DarkMarketListingResponse]
    total: int
    page: int
    page_size: int


class DarkMarketForceDelistResponse(ApiModel):
    status: str


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
    state: str | None = None
    stack: int | None = None
    street_contribution: int | None = None
    total_contribution: int | None = None
    total_points: int | None = None
    retired_at_round: int | None = None
    hearts: int | None = None


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
    button_seat: int | None = None
    current_seat: int | None = None
    board: list[str] = Field(default_factory=list)
    pot: int = 0
    action_deadline: AwareDatetime | None = None
    to_call: int = 0
    legal_actions: list[str] = Field(default_factory=list)
    mode: str | None = None
    round_number: int = 0
    maximum_rounds: int = 0


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
    global_completion_reward: int = Field(default=6, ge=0, le=999)
    submission_approval_reward: int = Field(default=10, ge=0, le=999)
    tipping_duration_seconds: int = Field(default=120, ge=10, le=3600)


class SetRandomEventSettingsRequest(RandomEventSettingsResponse):
    submission_enabled: bool | None = None
    submission_draft_timeout_minutes: int | None = Field(default=None, ge=1, le=1440)
    submission_max_participants: int | None = Field(default=None, ge=1, le=999)
    submission_default_target_rounds: int | None = Field(default=None, ge=1, le=999)
    submission_default_event_reward: int | None = Field(default=None, ge=0, le=999)
    global_completion_reward: int | None = Field(default=None, ge=0, le=999)
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
    single_answer_timeout_seconds: int = Field(ge=1, le=600)
    single_decision_timeout_seconds: int = Field(ge=1, le=600)
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
    has_details: bool = False


class PaginatedRandomEventSchedulesResponse(ApiModel):
    items: list[RandomEventScheduleResponse]
    page: int
    page_size: int
    total: int
    pages: int


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
    command: str
    status: str
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None


class CompleteWorkerCommandRequest(ApiModel):
    worker_id: str = Field(min_length=1, max_length=255)
    lease_token: UUID
    status: Literal["completed", "failed"]
    now: AwareDatetime
