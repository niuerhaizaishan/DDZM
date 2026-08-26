from datetime import datetime
from secrets import compare_digest
from typing import Annotated, Callable, Literal
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from uvicorn import Config, Server

from dzmm_bot.runtime.contracts import (
    InboundMessage,
    MessageReference,
    WorkerHeartbeat,
)
from dzmm_bot.runtime.settings import Settings
from dzmm_bot.ai.impressions import AIImpressionOperation

from .api_models import (
    AcceptedResponse,
    AIClaimResponse,
    AIConversationMessageResponse,
    AIKnowledgeCardResponse,
    AIActivityFactResponse,
    AIPlayerImpressionResponse,
    AIMemoryClaimResponse,
    AIMemoryCompleteRequest,
    AIMemoryFailedRequest,
    AIImpressionCandidateResponse,
    AIImpressionEntryResponse,
    AICompleteRequest,
    AIFailedRequest,
    AIAssistantSettingsResponse,
    AIPlayerMemoryResponse,
    AIRankQuotaResponse,
    ActivityLevelRuleModel,
    ActivitySettingsResponse,
    AdminStatusResponse,
    ClaimRequest,
    CompleteWorkerCommandRequest,
    CompleteProfileImageUploadRequest,
    CommandDefinitionResponse,
    CommandTemplateResponse,
    CreateGroupChatRequest,
    CreateDepartmentRequest,
    CreateAIPlayerImpressionRequest,
    CreateItemRequest,
    UpdateItemRequest,
    CreateProfileImageUploadRequest,
    DailyJobsRequest,
    DirectChatSyncRequest,
    DirectInboundRoomsResponse,
    DeleteGroupChatRequest,
    FailedRequest,
    FailProfileImageUploadRequest,
    GameSettingsResponse,
    GroupChatResponse,
    GroupChatRuntimeResponse,
    GroupChatTargetResponse,
    PersonalProfileResponse,
    ProfileImageCleanupClaimResponse,
    ProfileImageUploadClaimResponse,
    ProfileImageUploadStatusResponse,
    ProfileSettingsResponse,
    PerformanceExtensionResponse,
    PerformanceAuditResponse,
    PerformanceResponse,
    PerformanceSettingsResponse,
    PerformanceTipResponse,
    ReviewPerformanceExtensionRequest,
    ReviewPerformanceRequest,
    UpdatePerformanceSettingsRequest,
    HealthResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    InboundRequest,
    InboundResponse,
    ManualLoginActorRequest,
    ManualLoginLeaseResponse,
    OutboundClaimResponse,
    OutboundRecallClaimResponse,
    NumberBombSettingsResponse,
    TexasHoldemSettingsResponse,
    DarkMarketSettingsResponse,
    DarkMarketRankLimitResponse,
    SetDarkMarketSettingsRequest,
    ShopAdminActivityResponse,
    ShopSceneClaimResponse,
    DarkMarketListingResponse,
    DarkMarketBidResponse,
    PaginatedDarkMarketListingsResponse,
    DarkMarketForceDelistResponse,
    RedPacketSettingsResponse,
    GameplayParticipantResponse,
    GameplaySummariesResponse,
    GameplaySummaryResponse,
    QueueCountsResponse,
    RecalledRequest,
    SentRequest,
    SetCommandEnabledRequest,
    SetCommandTemplateRequest,
    SetActivitySettingsRequest,
    SetNumberBombSettingsRequest,
    SetTexasHoldemSettingsRequest,
    SetRedPacketSettingsRequest,
    SetAIAssistantSettingsRequest,
    SetAIKnowledgeCardRequest,
    UpdateAIPlayerImpressionRequest,
    SetGameSettingsRequest,
    SyncGroupChatRuntimeRequest,
    SetPersonalProfileRequest,
    SetProfileSettingsRequest,
    RandomEventSettingsResponse,
    SetRandomEventSettingsRequest,
    RandomEventSceneResponse,
    PaginatedRandomEventScenesResponse,
    CreateRandomEventSceneRequest,
    CreateTodayRandomEventRequest,
    UpdateRandomEventSceneRequest,
    RandomEventScheduleResponse,
    RandomEventDetailsResponse,
    RescheduleRandomEventRequest,
    HideAndSeekSettingsResponse,
    SetHideAndSeekSettingsRequest,
    MemoryAssessmentSettingsResponse,
    SetMemoryAssessmentSettingsRequest,
    MemoryAssessmentLevelRuleModel,
    UndercoverRoleRuleModel,
    UndercoverSettingsResponse,
    SetUndercoverSettingsRequest,
    UndercoverSessionResponse,
    BlameGameDurationRuleModel,
    BlameGameSettingsResponse,
    SetBlameGameSettingsRequest,
    BlameIncidentCardResponse,
    PaginatedBlameIncidentCardsResponse,
    PaginatedBalanceTransactionsResponse,
    EmployeeGroupMessageResponse,
    PaginatedEmployeeGroupMessagesResponse,
    CreateBlameIncidentCardRequest,
    UpdateBlameIncidentCardRequest,
    BlameGameSessionResponse,
    BlameGamePlayerResponse,
    BlameGameIncidentResponse,
    BlameGameHolderResponse,
    BalanceTransactionResponse,
    HideAndSeekSceneResponse,
    PaginatedHideAndSeekScenesResponse,
    CreateHideAndSeekSceneRequest,
    UpdateHideAndSeekSceneRequest,
    ItemResponse,
    PaginatedItemsResponse,
    PaginatedDepartmentsResponse,
    PaginatedDepartmentRequestsResponse,
    PaginatedPromotionRequestsResponse,
    PaginatedUsersResponse,
    PromotionRequestResponse,
    DepartmentRequestResponse,
    RankResponse,
    DepartmentResponse,
    SetBoardMembershipRequest,
    UpdateDepartmentRequest,
    UpdateGroupChatRequest,
    UpdateRankRequest,
    UserProfileResponse,
    UserResponse,
    WorkerCommandRequest,
    WorkerCommandResponse,
)
from .database import create_session_factory
from .commands import GroupCommandHandler
from .repository import (
    ActivityLevelRule,
    CoreRepository,
    GroupChatConflict,
    GroupChatRuntimeUpdate,
    ManualLoginBusyError,
    ManualLoginLease,
    ManualLoginOwnerError,
    MemoryAssessmentLevelRule,
    UndercoverRoleRule,
    format_employee_number,
)
from .reply_templates import definitions_for_command, template_definition
from .performance import HttpCoverImageValidator
from .schema import WorkerCommandRecord, WorkerInstanceRecord, beijing_now
from .service import CoreService


def create_server(repository: CoreRepository, settings: Settings) -> Server:
    _ensure_primary_group(repository, settings.chat_url)
    config = Config(
        create_app(
            repository,
            settings.core_token,
            require_group_chat_bootstrap=True,
        ),
        host="127.0.0.1",
        port=settings.core_api_port,
    )
    return Server(config)


def create_app_from_environment() -> FastAPI:
    settings = Settings.from_environment()
    repository = CoreRepository(
        create_session_factory(settings.database_url),
        preserve_long_group_messages=settings.bot_api_token is not None,
    )
    _ensure_primary_group(repository, settings.chat_url)
    return create_app(
        repository,
        settings.core_token,
        require_group_chat_bootstrap=True,
    )


def create_app(
    repository: CoreRepository,
    core_token: str,
    *,
    clock: Callable[[], datetime] = beijing_now,
    require_group_chat_bootstrap: bool = False,
    cover_image_validator=None,
) -> FastAPI:
    app = FastAPI()
    if cover_image_validator is None:
        cover_image_validator = HttpCoverImageValidator(httpx.Client(timeout=5))
    service = CoreService(
        repository,
        GroupCommandHandler(repository),
        cover_image_validator=cover_image_validator,
    )

    def authorize(x_core_token: Annotated[str | None, Header()] = None) -> None:
        if x_core_token is None or not compare_digest(x_core_token, core_token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")

    @app.post("/internal/inbound", response_model=InboundResponse)
    def receive_inbound(
        request: InboundRequest, _: Annotated[None, Depends(authorize)]
    ) -> InboundResponse:
        reference = request.reference
        result = service.receive_inbound(
            InboundMessage(
                platform_message_id=request.platform_message_id,
                sender_platform_id=request.sender_platform_id,
                content=request.content,
                received_at=request.received_at,
                source_type=request.source_type,
                chatroom_id=request.chatroom_id,
                reference=None
                if reference is None
                else MessageReference(
                    message_id=reference.message_id,
                    sender_platform_id=reference.sender_platform_id,
                    content_type=reference.content_type,
                    image_url=reference.image_url,
                    alt=reference.alt,
                    width=reference.width,
                    height=reference.height,
                    blurhash=reference.blurhash,
                    text=reference.text,
                ),
                content_type=request.content_type,
                image_url=request.image_url,
                image_alt=request.image_alt,
                image_width=request.image_width,
                image_height=request.image_height,
            )
        )
        return InboundResponse(
            message_id=result.message_id, accepted=result.inserted
        )

    @app.get("/internal/group-chats", response_model=list[GroupChatResponse])
    def group_chats(
        _: Annotated[None, Depends(authorize)],
        include_deleted: bool = False,
    ) -> list[GroupChatResponse]:
        runtime = {
            item.group_chat_id: item
            for item in repository.group_chat_runtime_states()
        }
        return [
            _group_chat_response(group, runtime.get(group.id))
            for group in repository.list_group_chats(include_deleted)
        ]

    @app.post(
        "/internal/group-chats",
        response_model=GroupChatResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_group_chat(
        request: CreateGroupChatRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> GroupChatResponse:
        try:
            group = repository.create_group_chat(
                request.name,
                request.chat_url,
                request.listening_enabled,
                request.games_enabled,
                request.random_events_enabled,
                request.announcements_enabled,
                request.now,
                enabled_game_types=request.enabled_game_types,
                adult_shop_enabled=request.adult_shop_enabled,
                performances_enabled=request.performances_enabled,
            )
        except (ValueError, GroupChatConflict) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        runtime = {
            item.group_chat_id: item
            for item in repository.group_chat_runtime_states()
        }.get(group.id)
        return _group_chat_response(group, runtime)

    @app.get(
        "/internal/group-chats/targets",
        response_model=list[GroupChatTargetResponse],
    )
    def group_chat_targets(
        _: Annotated[None, Depends(authorize)],
    ) -> list[GroupChatTargetResponse]:
        return [
            GroupChatTargetResponse(
                group_chat_id=target.group_chat_id,
                chatroom_id=target.chatroom_id,
                chat_url=target.chat_url,
            )
            for target in repository.enabled_group_targets()
        ]

    @app.post("/internal/group-chats/runtime", response_model=AcceptedResponse)
    def sync_group_chat_runtime(
        request: SyncGroupChatRuntimeRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        try:
            repository.record_group_chat_runtime(
                request.worker_id,
                tuple(
                    GroupChatRuntimeUpdate(
                        group_chat_id=item.group_chat_id,
                        connection_state=item.connection_state,
                        last_connected_at=item.last_connected_at,
                        last_inbound_at=item.last_inbound_at,
                        last_outbound_at=item.last_outbound_at,
                        last_error_summary=item.last_error_summary,
                    )
                    for item in request.statuses
                ),
                request.now,
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        return AcceptedResponse(accepted=True)

    @app.patch(
        "/internal/group-chats/{group_id}", response_model=GroupChatResponse
    )
    def update_group_chat(
        group_id: UUID,
        request: UpdateGroupChatRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> GroupChatResponse:
        try:
            group = repository.update_group_chat(
                group_id,
                name=request.name,
                chat_url=request.chat_url,
                listening_enabled=request.listening_enabled,
                games_enabled=request.games_enabled,
                enabled_game_types=request.enabled_game_types,
                random_events_enabled=request.random_events_enabled,
                announcements_enabled=request.announcements_enabled,
                adult_shop_enabled=request.adult_shop_enabled,
                performances_enabled=request.performances_enabled,
                now=request.now,
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except (ValueError, GroupChatConflict) as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        runtime = {
            item.group_chat_id: item
            for item in repository.group_chat_runtime_states()
        }.get(group.id)
        return _group_chat_response(group, runtime)

    @app.get(
        "/internal/game/performances/settings",
        response_model=PerformanceSettingsResponse,
    )
    def performance_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> PerformanceSettingsResponse:
        current = repository.get_performance_settings()
        return PerformanceSettingsResponse(
            maximum_duration_minutes=current.maximum_duration_minutes,
            version=current.version,
        )

    @app.patch(
        "/internal/game/performances/settings",
        response_model=PerformanceSettingsResponse,
    )
    def update_performance_settings(
        request: UpdatePerformanceSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> PerformanceSettingsResponse:
        current = repository.update_performance_settings(
            request.maximum_duration_minutes
        )
        return PerformanceSettingsResponse(
            maximum_duration_minutes=current.maximum_duration_minutes,
            version=current.version,
        )

    @app.get(
        "/internal/game/performances", response_model=list[PerformanceResponse]
    )
    def list_performances(
        _: Annotated[None, Depends(authorize)], state: str | None = None
    ) -> list[PerformanceResponse]:
        return [
            _performance_response(view)
            for view in repository.list_performances(state)
        ]

    @app.get(
        "/internal/game/performances/{performance_id}",
        response_model=PerformanceResponse,
    )
    def performance_detail(
        performance_id: UUID, _: Annotated[None, Depends(authorize)]
    ) -> PerformanceResponse:
        view = repository.performance_details(performance_id)
        if view is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "performance_not_found")
        return _performance_response(view)

    @app.post(
        "/internal/game/performances/{performance_id}/approve",
        response_model=PerformanceResponse,
    )
    def approve_performance(
        performance_id: UUID,
        request: ReviewPerformanceRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> PerformanceResponse:
        try:
            view = repository.review_performance(
                performance_id, True, request.actor, request.now
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        return _performance_response(view)

    @app.post(
        "/internal/game/performances/{performance_id}/reject",
        response_model=PerformanceResponse,
    )
    def reject_performance(
        performance_id: UUID,
        request: ReviewPerformanceRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> PerformanceResponse:
        try:
            view = repository.review_performance(
                performance_id, False, request.actor, request.now, request.reason
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        return _performance_response(view)

    @app.post(
        "/internal/game/performances/{performance_id}/cancel",
        response_model=PerformanceResponse,
    )
    def cancel_performance(
        performance_id: UUID,
        request: ReviewPerformanceRequest,
        _: Annotated[None, Depends(authorize)],
        force: bool = False,
    ) -> PerformanceResponse:
        try:
            view = repository.cancel_performance_by_admin(
                performance_id,
                request.actor,
                request.reason or "",
                request.now,
                force=force,
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except PermissionError as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error))
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        return _performance_response(view)

    @app.post(
        "/internal/game/performance-extensions/{request_id}/approve",
        response_model=PerformanceResponse,
    )
    def approve_performance_extension(
        request_id: UUID,
        request: ReviewPerformanceExtensionRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> PerformanceResponse:
        try:
            result = repository.review_performance_postponement(
                request_id,
                True,
                request.actor,
                request.now,
                allow_post_preview=request.allow_post_preview,
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except PermissionError as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error))
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        if result.reservation is None:
            raise HTTPException(status.HTTP_409_CONFLICT, result.status)
        return _performance_response(result.reservation)

    @app.post(
        "/internal/game/performance-extensions/{request_id}/reject",
        response_model=PerformanceResponse,
    )
    def reject_performance_extension(
        request_id: UUID,
        request: ReviewPerformanceExtensionRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> PerformanceResponse:
        try:
            result = repository.review_performance_postponement(
                request_id,
                False,
                request.actor,
                request.now,
                request.reason,
                allow_post_preview=request.allow_post_preview,
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except PermissionError as error:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(error))
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        if result.reservation is None:
            raise HTTPException(status.HTTP_409_CONFLICT, result.status)
        return _performance_response(result.reservation)

    @app.delete(
        "/internal/group-chats/{group_id}", response_model=GroupChatResponse
    )
    def delete_group_chat(
        group_id: UUID,
        request: DeleteGroupChatRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> GroupChatResponse:
        try:
            group = repository.soft_delete_group_chat(group_id, request.now)
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        except GroupChatConflict as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        runtime = {
            item.group_chat_id: item
            for item in repository.group_chat_runtime_states()
        }.get(group.id)
        return _group_chat_response(group, runtime)

    @app.post("/internal/direct-chats/sync", response_model=AcceptedResponse)
    def sync_direct_chats(
        request: DirectChatSyncRequest, _: Annotated[None, Depends(authorize)]
    ) -> AcceptedResponse:
        repository.upsert_direct_chats(
            [(room.platform_user_id, room.chatroom_id) for room in request.rooms],
            request.now,
        )
        return AcceptedResponse(accepted=True)

    @app.get(
        "/internal/direct-inbound/rooms",
        response_model=DirectInboundRoomsResponse,
    )
    def direct_inbound_rooms(
        _: Annotated[None, Depends(authorize)],
    ) -> DirectInboundRoomsResponse:
        return DirectInboundRoomsResponse(
            chatroom_ids=list(repository.direct_inbound_chatroom_ids(clock()))
        )

    @app.post(
        "/internal/outbound/claim",
        response_model=OutboundClaimResponse | None,
    )
    def claim_outbound(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> OutboundClaimResponse | None:
        record = repository.claim_outbound(
            request.worker_id,
            request.now,
            request.lease_seconds,
            tuple(request.excluded_delivery_keys),
            request.required_delivery_key,
        )
        if record is None:
            return None
        return OutboundClaimResponse(
            id=record.id,
            inbound_message_id=record.inbound_message_id,
            group_chat_id=record.group_chat_id,
            text=record.text,
            content_type=record.content_type,
            image_url=record.image_url,
            image_alt=record.image_alt,
            lease_token=record.lease_token,
            lease_expires_at=record.lease_expires_at,
            attempt_count=record.attempt_count,
            destination_chatroom_id=record.destination_chatroom_id,
            delivery_key=record.delivery_key,
            delivery_kind=record.delivery_kind,
            reference_message_id=record.reference_message_id,
            reference_sender_platform_id=record.reference_sender_platform_id,
            reference_content_type=record.reference_content_type,
            reference_text=record.reference_text,
            recall_after_seconds=record.recall_after_seconds,
        )

    @app.post(
        "/internal/outbound/{message_id}/sent", response_model=AcceptedResponse
    )
    def confirm_sent(
        message_id: UUID,
        request: SentRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        accepted = repository.confirm_sent(
            message_id,
            request.worker_id,
            request.lease_token,
            request.platform_sent_id,
            request.now,
        )
        return AcceptedResponse(accepted=accepted)

    @app.post(
        "/internal/profile-image-uploads/claim",
        response_model=ProfileImageUploadClaimResponse | None,
    )
    def claim_profile_image_upload(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> ProfileImageUploadClaimResponse | None:
        claim = repository.claim_profile_image_upload(
            request.worker_id, request.now, request.lease_seconds
        )
        if claim is None:
            return None
        return ProfileImageUploadClaimResponse(
            id=claim.id,
            temp_path=claim.temp_path,
            original_filename=claim.original_filename,
            mime_type=claim.mime_type,
            expected_profile_version=claim.expected_profile_version,
            lease_token=claim.lease_token,
            attempt_count=claim.attempt_count,
        )

    @app.post(
        "/internal/game/users/{platform_id}/profile-image-uploads",
        response_model=ProfileImageUploadStatusResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_profile_image_upload(
        platform_id: str,
        request: CreateProfileImageUploadRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> ProfileImageUploadStatusResponse:
        try:
            record = repository.create_profile_image_upload(
                platform_id,
                request.temp_path,
                request.original_filename,
                request.mime_type,
                request.now,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return ProfileImageUploadStatusResponse(
            id=record.id,
            platform_id=platform_id,
            status=record.status,
            result_url=record.result_url,
            failure_summary=record.failure_summary,
            expected_profile_version=record.expected_profile_version,
        )

    @app.get(
        "/internal/profile-image-uploads/{task_id}",
        response_model=ProfileImageUploadStatusResponse,
    )
    def profile_image_upload_status(
        task_id: UUID, _: Annotated[None, Depends(authorize)]
    ) -> ProfileImageUploadStatusResponse:
        record = repository.get_profile_image_upload(task_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")
        user = repository.find_user_by_id(record.user_id)
        if user is None:
            raise RuntimeError("upload user disappeared")
        return ProfileImageUploadStatusResponse(
            id=record.id,
            platform_id=user.platform_id,
            status=record.status,
            result_url=record.result_url,
            failure_summary=record.failure_summary,
            expected_profile_version=record.expected_profile_version,
        )

    @app.post(
        "/internal/profile-image-uploads/{task_id}/completed",
        response_model=AcceptedResponse,
    )
    def complete_profile_image_upload(
        task_id: UUID,
        request: CompleteProfileImageUploadRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.complete_profile_image_upload(
            task_id, request.worker_id, request.lease_token,
            request.result_url, request.now,
        ))

    @app.post(
        "/internal/profile-image-uploads/{task_id}/failed",
        response_model=AcceptedResponse,
    )
    def fail_profile_image_upload(
        task_id: UUID,
        request: FailProfileImageUploadRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.fail_profile_image_upload(
            task_id, request.worker_id, request.lease_token,
            request.failure_summary, request.now,
        ))

    @app.post(
        "/internal/profile-image-cleanups/claim",
        response_model=ProfileImageCleanupClaimResponse | None,
    )
    def claim_profile_image_cleanup(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> ProfileImageCleanupClaimResponse | None:
        claim = repository.claim_profile_image_cleanup(
            request.worker_id, request.now, request.lease_seconds
        )
        if claim is None:
            return None
        return ProfileImageCleanupClaimResponse(
            id=claim.id, temp_path=claim.temp_path, lease_token=claim.lease_token
        )

    @app.post(
        "/internal/profile-image-cleanups/{task_id}/completed",
        response_model=AcceptedResponse,
    )
    def complete_profile_image_cleanup(
        task_id: UUID,
        request: RecalledRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.complete_profile_image_cleanup(
            task_id, request.worker_id, request.lease_token, request.now
        ))

    @app.post(
        "/internal/outbound/{message_id}/failed", response_model=AcceptedResponse
    )
    def mark_outbound_failed(
        message_id: UUID,
        request: FailedRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        accepted = repository.mark_outbound_failed(
            message_id,
            request.worker_id,
            request.lease_token,
            request.now,
        )
        return AcceptedResponse(accepted=accepted)

    @app.post(
        "/internal/outbound/{message_id}/retry", response_model=AcceptedResponse
    )
    def release_outbound(
        message_id: UUID,
        request: FailedRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        accepted = repository.release_outbound(
            message_id,
            request.worker_id,
            request.lease_token,
            request.now,
        )
        return AcceptedResponse(accepted=accepted)

    @app.post(
        "/internal/outbound/recall/claim",
        response_model=OutboundRecallClaimResponse | None,
    )
    def claim_outbound_recall(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> OutboundRecallClaimResponse | None:
        record = repository.claim_outbound_recall(
            request.worker_id, request.now, request.lease_seconds
        )
        if record is None:
            return None
        if record.platform_sent_id is None:
            raise RuntimeError("待撤回消息缺少平台消息 ID")
        return OutboundRecallClaimResponse(
            id=record.id,
            platform_sent_id=record.platform_sent_id,
            lease_token=record.recall_lease_token,
            lease_expires_at=record.recall_lease_expires_at,
            attempt_count=record.recall_attempt_count,
        )

    @app.post(
        "/internal/outbound/{message_id}/recalled", response_model=AcceptedResponse
    )
    def confirm_outbound_recalled(
        message_id: UUID,
        request: RecalledRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        accepted = repository.confirm_outbound_recalled(
            message_id, request.worker_id, request.lease_token, request.now
        )
        return AcceptedResponse(accepted=accepted)

    @app.post("/internal/heartbeat", response_model=HeartbeatResponse)
    def record_heartbeat(
        request: HeartbeatRequest, _: Annotated[None, Depends(authorize)]
    ) -> HeartbeatResponse:
        record = repository.record_worker_heartbeat(
            WorkerHeartbeat(
                request.worker_id,
                request.login_state,
                request.recorded_at,
                listening=request.listening,
                account_display_name=request.account_display_name,
                bot_delivery_state=request.bot_delivery_state,
                bot_delivery_error=request.bot_delivery_error,
            )
        )
        return _heartbeat_response(record)

    @app.get("/internal/login-state", response_model=HeartbeatResponse | None)
    def login_state(
        _: Annotated[None, Depends(authorize)],
    ) -> HeartbeatResponse | None:
        record = _latest_heartbeat(repository)
        return None if record is None else _heartbeat_response(record)

    @app.get("/internal/status", response_model=AdminStatusResponse)
    def admin_status(
        _: Annotated[None, Depends(authorize)],
    ) -> AdminStatusResponse:
        record = _latest_heartbeat(repository)
        return AdminStatusResponse(
            state="unknown" if record is None else record.login_state,
            last_heartbeat=None if record is None else record.recorded_at,
            listening=None if record is None else record.listening,
            listening_desired=None if record is None else record.listening_desired,
            bot_delivery_state=(
                "unknown" if record is None else record.bot_delivery_state
            ),
            bot_delivery_error=None if record is None else record.bot_delivery_error,
            queue_counts=QueueCountsResponse(**repository.queue_counts()),
        )

    @app.get(
        "/internal/game/commands", response_model=list[CommandDefinitionResponse]
    )
    def game_commands(
        _: Annotated[None, Depends(authorize)],
    ) -> list[CommandDefinitionResponse]:
        return [
            CommandDefinitionResponse(
                command=record.command,
                description=record.description,
                enabled=record.enabled,
                templates=[
                    _template_response(
                        definition,
                        repository.get_reply_template(
                            definition.command, definition.scenario
                        ),
                    )
                    for definition in definitions_for_command(record.command)
                ],
            )
            for record in repository.list_command_definitions()
        ]

    @app.patch(
        "/internal/game/commands", response_model=CommandDefinitionResponse
    )
    def set_game_command_enabled(
        request: SetCommandEnabledRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> CommandDefinitionResponse:
        if not repository.set_command_enabled(request.command, request.enabled):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown command")
        record = next(
            record
            for record in repository.list_command_definitions()
            if record.command == request.command
        )
        return CommandDefinitionResponse(
            command=record.command,
            description=record.description,
            enabled=record.enabled,
            templates=[
                _template_response(
                    definition,
                    repository.get_reply_template(
                        definition.command, definition.scenario
                    ),
                )
                for definition in definitions_for_command(record.command)
            ],
        )

    @app.patch(
        "/internal/game/command-templates", response_model=CommandTemplateResponse
    )
    def set_game_command_template(
        request: SetCommandTemplateRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> CommandTemplateResponse:
        try:
            record = repository.set_reply_template(
                request.command, request.scenario, request.template
            )
            definition = template_definition(request.command, request.scenario)
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _template_response(definition, record)

    @app.get("/internal/game/ranks", response_model=list[RankResponse])
    def game_ranks(
        _: Annotated[None, Depends(authorize)],
    ) -> list[RankResponse]:
        return [_rank_response(rank) for rank in repository.list_ranks()]

    @app.patch("/internal/game/ranks/{rank_id}", response_model=RankResponse)
    def update_game_rank(
        rank_id: UUID,
        request: UpdateRankRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RankResponse:
        try:
            rank = repository.update_rank(rank_id, **request.model_dump())
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        if rank is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "rank not found")
        return _rank_response(rank)

    @app.get(
        "/internal/game/departments", response_model=PaginatedDepartmentsResponse
    )
    def game_departments(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedDepartmentsResponse:
        departments, total = repository.list_departments_page(page, page_size)
        return PaginatedDepartmentsResponse(
            items=[_department_response(department) for department in departments],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.post(
        "/internal/game/departments",
        response_model=DepartmentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_game_department(
        request: CreateDepartmentRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> DepartmentResponse:
        try:
            department = repository.create_department(
                request.name, request.description
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _department_response(department)

    @app.put(
        "/internal/game/departments/{department_id}", response_model=DepartmentResponse
    )
    def update_game_department(
        department_id: UUID,
        request: UpdateDepartmentRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> DepartmentResponse:
        try:
            department = repository.update_department(
                department_id, **request.model_dump()
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        if department is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "department not found")
        return _department_response(department)

    @app.delete(
        "/internal/game/departments/{department_id}", response_model=AcceptedResponse
    )
    def delete_game_department(
        department_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        try:
            deleted = repository.delete_department(department_id)
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "department not found")
        return AcceptedResponse(accepted=True)

    @app.get(
        "/internal/game/promotions",
        response_model=PaginatedPromotionRequestsResponse,
    )
    def game_promotions(
        _: Annotated[None, Depends(authorize)],
        state: str | None = Query(None, pattern="^(pending|approved|rejected|expired)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedPromotionRequestsResponse:
        records, total = repository.list_promotion_requests_page(
            state, page, page_size, clock()
        )
        return PaginatedPromotionRequestsResponse(
            items=[_promotion_request_response(record) for record in records],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.get(
        "/internal/game/department-requests",
        response_model=PaginatedDepartmentRequestsResponse,
    )
    def game_department_requests(
        _: Annotated[None, Depends(authorize)],
        state: str | None = Query(None, pattern="^(pending|approved|rejected|expired)$"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedDepartmentRequestsResponse:
        records, total = repository.list_department_requests_page(
            state, page, page_size, clock()
        )
        return PaginatedDepartmentRequestsResponse(
            items=[_department_request_response(record) for record in records],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.post(
        "/internal/game/users/{platform_id}/board-membership",
        response_model=UserProfileResponse,
    )
    def set_board_membership(
        platform_id: str,
        request: SetBoardMembershipRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> UserProfileResponse:
        profile = repository.set_board_membership(platform_id, request.member)
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        return _user_profile_response(profile)

    @app.get(
        "/internal/game/users/{platform_id}/balance-transactions",
        response_model=PaginatedBalanceTransactionsResponse,
    )
    def balance_transactions(
        platform_id: str,
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedBalanceTransactionsResponse:
        ledger = repository.list_balance_transactions_page(platform_id, page, page_size)
        if ledger is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        return PaginatedBalanceTransactionsResponse(
            platform_id=ledger.platform_id,
            display_name=ledger.display_name,
            current_balance=ledger.current_balance,
            items=[
                BalanceTransactionResponse(
                    id=item.id,
                    amount=item.amount,
                    source=item.source,
                    source_label=item.source_label,
                    occurred_at=item.occurred_at,
                    balance_after=item.balance_after,
                )
                for item in ledger.items
            ],
            page=page,
            page_size=page_size,
            total=ledger.total,
            pages=(ledger.total + page_size - 1) // page_size,
        )

    @app.get("/internal/game/users", response_model=PaginatedUsersResponse)
    def game_users(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedUsersResponse:
        records, total = repository.list_users_page(page, page_size)
        return PaginatedUsersResponse(
            items=[
                _user_response(repository.get_user_profile(record.platform_id))
                for record in records
            ],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.get(
        "/internal/game/users/{platform_id}/group-messages",
        response_model=PaginatedEmployeeGroupMessagesResponse,
    )
    def employee_group_messages(
        platform_id: str,
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        group_chat_id: UUID | None = Query(None),
    ) -> PaginatedEmployeeGroupMessagesResponse:
        history = repository.list_employee_group_messages_page(
            platform_id, page, page_size, group_chat_id
        )
        if history is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        return PaginatedEmployeeGroupMessagesResponse(
            platform_id=history.platform_id,
            display_name=history.display_name,
            items=[
                EmployeeGroupMessageResponse(
                    id=item.id,
                    group_chat_id=item.group_chat_id,
                    group_name=item.group_name,
                    content=item.content,
                    received_at=item.received_at,
                )
                for item in history.items
            ],
            page=page,
            page_size=page_size,
            total=history.total,
            pages=(history.total + page_size - 1) // page_size,
        )

    @app.get("/internal/game/items", response_model=PaginatedItemsResponse)
    def game_items(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedItemsResponse:
        records, total = repository.list_active_items_page(page, page_size)
        return PaginatedItemsResponse(
            items=[_item_response(record) for record in records],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.post(
        "/internal/game/items", response_model=ItemResponse, status_code=201
    )
    def create_game_item(
        request: CreateItemRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> ItemResponse:
        return _item_response(
            repository.add_item(
                request.name, request.description, request.price, request.stock
            )
        )

    @app.patch(
        "/internal/game/items/{public_number}", response_model=ItemResponse
    )
    def update_game_item(
        public_number: int,
        request: UpdateItemRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> ItemResponse:
        try:
            record = repository.update_shop_item(
                public_number,
                description=request.description,
                enabled=request.enabled,
                minimum_rank_order=request.minimum_rank_order,
                unlimited_stock=request.unlimited_stock,
                stock=request.stock,
            )
        except LookupError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error))
        return _item_response(record)

    @app.get(
        "/internal/game/shop/activity", response_model=ShopAdminActivityResponse
    )
    def shop_activity(
        _: Annotated[None, Depends(authorize)],
        limit: int = Query(100, ge=1, le=500),
    ) -> ShopAdminActivityResponse:
        return ShopAdminActivityResponse(
            **repository.list_shop_admin_activity(limit)
        )

    @app.post(
        "/internal/game/shop/scene-jobs/{job_id}/retry",
        response_model=AcceptedResponse,
    )
    def retry_shop_scene_job(
        job_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.retry_shop_scene_job(job_id))

    @app.post(
        "/internal/game/shop/common-states/{state_id}/end",
        response_model=AcceptedResponse,
    )
    def end_shop_common_state(
        state_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.force_end_shop_common_state(state_id, clock())
        )

    @app.get("/internal/game/settings", response_model=GameSettingsResponse)
    def game_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> GameSettingsResponse:
        return _game_settings_response(repository.get_game_settings())

    @app.patch("/internal/game/settings", response_model=GameSettingsResponse)
    def set_game_settings(
        request: SetGameSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> GameSettingsResponse:
        try:
            record = repository.set_game_settings(
                request.currency_name,
                request.onboarding_bonus,
                request.checkin_reward,
                request.weekly_attendance_reward,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _game_settings_response(record)

    @app.get(
        "/internal/game/profile-settings", response_model=ProfileSettingsResponse
    )
    def profile_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> ProfileSettingsResponse:
        settings = repository.get_profile_settings()
        return ProfileSettingsResponse(
            edit_cost=settings.edit_cost,
            shared_labor=settings.shared_labor,
            version=settings.version,
        )

    @app.patch(
        "/internal/game/profile-settings", response_model=ProfileSettingsResponse
    )
    def set_profile_settings(
        request: SetProfileSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> ProfileSettingsResponse:
        try:
            settings = repository.set_profile_settings(
                request.edit_cost,
                request.shared_labor,
                expected_version=request.version,
            )
        except ValueError as error:
            code = (
                status.HTTP_409_CONFLICT
                if "其他管理员" in str(error)
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(code, str(error))
        return ProfileSettingsResponse(
            edit_cost=settings.edit_cost,
            shared_labor=settings.shared_labor,
            version=settings.version,
        )

    @app.get(
        "/internal/game/users/{platform_id}/profile",
        response_model=PersonalProfileResponse,
    )
    def personal_profile(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> PersonalProfileResponse:
        user = repository.find_user(platform_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        latest_upload = repository.latest_profile_image_upload(platform_id)
        return PersonalProfileResponse(
            platform_id=user.platform_id,
            display_name=user.display_name,
            profile_text=user.profile_text,
            profile_image_url=user.profile_image_url,
            profile_version=user.profile_version,
            latest_upload=None if latest_upload is None else {
                "id": str(latest_upload.id),
                "status": latest_upload.status,
                "failure_summary": latest_upload.failure_summary,
            },
        )

    @app.put(
        "/internal/game/users/{platform_id}/profile",
        response_model=PersonalProfileResponse,
    )
    def set_personal_profile(
        platform_id: str,
        request: SetPersonalProfileRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> PersonalProfileResponse:
        try:
            saved = repository.set_personal_profile_by_admin(
                platform_id, request.profile_text
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        if not saved:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        user = repository.find_user(platform_id)
        if user is None:
            raise RuntimeError("saved profile user disappeared")
        return PersonalProfileResponse(
            platform_id=user.platform_id,
            display_name=user.display_name,
            profile_text=user.profile_text,
            profile_image_url=user.profile_image_url,
            profile_version=user.profile_version,
            latest_upload=None,
        )

    @app.delete(
        "/internal/game/users/{platform_id}/profile-image",
        response_model=PersonalProfileResponse,
    )
    def clear_personal_profile_image(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> PersonalProfileResponse:
        if not repository.set_profile_image_by_admin(platform_id, None):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        user = repository.find_user(platform_id)
        if user is None:
            raise RuntimeError("profile user disappeared")
        return PersonalProfileResponse(
            platform_id=user.platform_id,
            display_name=user.display_name,
            profile_text=user.profile_text,
            profile_image_url=user.profile_image_url,
            profile_version=user.profile_version,
            latest_upload=None,
        )

    @app.get(
        "/internal/game/ai-assistant/settings",
        response_model=AIAssistantSettingsResponse,
    )
    def ai_assistant_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> AIAssistantSettingsResponse:
        return _ai_assistant_settings_response(repository)

    @app.patch(
        "/internal/game/ai-assistant/settings",
        response_model=AIAssistantSettingsResponse,
    )
    def set_ai_assistant_settings(
        request: SetAIAssistantSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AIAssistantSettingsResponse:
        try:
            repository.set_ai_assistant_configuration(
                enabled=request.enabled,
                trigger_prefixes=request.trigger_prefixes,
                persona=request.persona,
                system_prompt=request.system_prompt,
                over_limit_reply=request.over_limit_reply,
                failure_reply=request.failure_reply,
                max_response_chars=request.max_response_chars,
                timeout_seconds=request.timeout_seconds,
                quotas=[(quota.rank_id, quota.daily_limit) for quota in request.quotas],
            )
            repository.set_ai_memory_settings(
                enabled=request.memory_enabled,
                gameplay_guide=repository.get_ai_memory_settings().gameplay_guide,
                extraction_prompt=request.extraction_prompt,
                history_limit=request.history_limit,
                max_memory_chars=request.max_memory_chars,
                batch_message_threshold=request.batch_message_threshold,
                max_entries_per_category=request.max_entries_per_category,
                candidate_expiry_days=request.candidate_expiry_days,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _ai_assistant_settings_response(repository)

    @app.get(
        "/internal/game/users/{platform_id}/ai-memory",
        response_model=AIPlayerMemoryResponse,
    )
    def ai_player_memory(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> AIPlayerMemoryResponse:
        return _ai_player_memory_response(repository, platform_id)

    @app.get(
        "/internal/game/ai-knowledge-cards",
        response_model=list[AIKnowledgeCardResponse],
    )
    def ai_knowledge_cards(
        _: Annotated[None, Depends(authorize)],
    ) -> list[AIKnowledgeCardResponse]:
        return [_ai_knowledge_card_response(card) for card in repository.list_ai_knowledge_cards()]

    @app.post(
        "/internal/game/ai-knowledge-cards",
        response_model=AIKnowledgeCardResponse,
    )
    def create_ai_knowledge_card(
        request: SetAIKnowledgeCardRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AIKnowledgeCardResponse:
        try:
            card = repository.create_ai_knowledge_card(
                request.topic, request.title, request.keywords, request.content,
                request.enabled, request.priority, beijing_now(),
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _ai_knowledge_card_response(card)

    @app.put(
        "/internal/game/ai-knowledge-cards/{card_id}",
        response_model=AIKnowledgeCardResponse,
    )
    def update_ai_knowledge_card(
        card_id: UUID,
        request: SetAIKnowledgeCardRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AIKnowledgeCardResponse:
        try:
            card = repository.update_ai_knowledge_card(
                card_id, request.topic, request.title, request.keywords,
                request.content, request.enabled, request.priority, beijing_now(),
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        if card is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge card not found")
        return _ai_knowledge_card_response(card)

    @app.delete(
        "/internal/game/ai-knowledge-cards/{card_id}",
        response_model=AcceptedResponse,
    )
    def delete_ai_knowledge_card(
        card_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        if not repository.delete_ai_knowledge_card(card_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge card not found")
        return AcceptedResponse(accepted=True)

    @app.post(
        "/internal/game/users/{platform_id}/ai-impressions",
        response_model=AIPlayerImpressionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_ai_player_impression(
        platform_id: str,
        request: CreateAIPlayerImpressionRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AIPlayerImpressionResponse:
        try:
            record = repository.create_ai_player_impression(
                platform_id, request.category, request.content, beijing_now()
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        return _ai_player_impression_response(record)

    @app.put(
        "/internal/game/users/{platform_id}/ai-impressions/{entry_id}",
        response_model=AIPlayerImpressionResponse,
    )
    def update_ai_player_impression(
        platform_id: str,
        entry_id: UUID,
        request: UpdateAIPlayerImpressionRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AIPlayerImpressionResponse:
        try:
            record = repository.update_ai_player_impression(
                platform_id,
                entry_id,
                request.category,
                request.content,
                request.pinned,
                beijing_now(),
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "impression not found")
        return _ai_player_impression_response(record)

    @app.delete(
        "/internal/game/users/{platform_id}/ai-impressions/{entry_id}",
        response_model=AcceptedResponse,
    )
    def delete_ai_player_impression(
        platform_id: str,
        entry_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        if not repository.delete_ai_player_impression(platform_id, entry_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "impression not found")
        return AcceptedResponse(accepted=True)

    @app.delete(
        "/internal/game/users/{platform_id}/ai-memory",
        response_model=AcceptedResponse,
    )
    def clear_ai_player_memory(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> AcceptedResponse:
        if not repository.clear_ai_player_memory(platform_id, beijing_now()):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        return AcceptedResponse(accepted=True)

    @app.post("/internal/ai/claim", response_model=AIClaimResponse | None)
    def claim_ai_request(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> AIClaimResponse | None:
        record = repository.claim_ai_request(
            request.worker_id, request.now, request.lease_seconds
        )
        if record is None:
            return None
        return AIClaimResponse(
            id=record.id,
            lease_token=record.lease_token,
            system_prompt=record.system_prompt,
            history_messages=[
                AIConversationMessageResponse(
                    role=message.role,
                    content=message.content,
                )
                for message in record.history_messages
            ],
            user_content=record.user_content,
            max_response_chars=record.max_response_chars,
            timeout_seconds=record.timeout_seconds,
        )

    @app.post(
        "/internal/ai/shop-scenes/claim", response_model=ShopSceneClaimResponse | None
    )
    def claim_shop_scene_job(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> ShopSceneClaimResponse | None:
        record = repository.claim_shop_scene_job(
            request.worker_id, request.now, request.lease_seconds
        )
        if record is None:
            return None
        return ShopSceneClaimResponse(
            id=record.id,
            lease_token=record.lease_token,
            system_prompt=record.system_prompt,
            user_content=record.user_content,
            max_response_chars=record.max_response_chars,
            timeout_seconds=record.timeout_seconds,
        )

    @app.post(
        "/internal/ai/shop-scenes/{job_id}/completed",
        response_model=AcceptedResponse,
    )
    def complete_shop_scene_job(
        job_id: UUID,
        request: AICompleteRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.complete_shop_scene_job(
                job_id,
                request.worker_id,
                request.lease_token,
                request.text,
                request.now,
            )
        )

    @app.post(
        "/internal/ai/shop-scenes/{job_id}/failed",
        response_model=AcceptedResponse,
    )
    def fail_shop_scene_job(
        job_id: UUID,
        request: AIFailedRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.fail_shop_scene_job(
                job_id,
                request.worker_id,
                request.lease_token,
                request.failure_summary,
                request.now,
            )
        )
    @app.post(
        "/internal/ai/{request_id}/completed", response_model=AcceptedResponse
    )
    def complete_ai_request(
        request_id: UUID,
        request: AICompleteRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.complete_ai_request(
                request_id,
                request.worker_id,
                request.lease_token,
                request.text,
                request.now,
            )
        )

    @app.post("/internal/ai/{request_id}/failed", response_model=AcceptedResponse)
    def fail_ai_request(
        request_id: UUID,
        request: AIFailedRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.fail_ai_request(
                request_id,
                request.worker_id,
                request.lease_token,
                request.failure_summary,
                request.now,
            )
        )

    @app.post("/internal/ai/memory/claim", response_model=AIMemoryClaimResponse | None)
    def claim_ai_memory_job(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> AIMemoryClaimResponse | None:
        record = repository.claim_ai_memory_job(
            request.worker_id, request.now, request.lease_seconds
        )
        if record is None:
            return None
        return AIMemoryClaimResponse(
            user_id=record.user_id,
            target_message_id=record.target_message_id,
            lease_token=record.lease_token,
            extraction_prompt=record.extraction_prompt,
            max_memory_chars=record.max_memory_chars,
            stable_entries=[
                AIImpressionEntryResponse(
                    id=entry.id,
                    category=entry.category,
                    content=entry.content,
                    pinned=entry.pinned,
                )
                for entry in record.stable_entries
            ],
            candidates=[
                AIImpressionCandidateResponse(
                    id=candidate.id,
                    category=candidate.category,
                    content=candidate.content,
                    support_batches=candidate.support_batches,
                    conflict_entry_id=candidate.conflict_entry_id,
                )
                for candidate in record.candidates
            ],
            source_messages=list(record.source_messages),
            source_message_count=record.source_message_count,
        )

    @app.post(
        "/internal/ai/memory/{user_id}/completed", response_model=AcceptedResponse
    )
    def complete_ai_memory_job(
        user_id: UUID,
        request: AIMemoryCompleteRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.complete_ai_memory_job(
                user_id,
                request.worker_id,
                request.lease_token,
                request.target_message_id,
                [
                    AIImpressionOperation(
                        action=operation.action,
                        category=operation.category,
                        content=operation.content,
                        candidate_id=operation.candidate_id,
                        entry_id=operation.entry_id,
                    )
                    for operation in request.operations
                ],
                request.source_message_count,
                request.now,
            )
        )

    @app.post("/internal/ai/memory/{user_id}/failed", response_model=AcceptedResponse)
    def fail_ai_memory_job(
        user_id: UUID,
        request: AIMemoryFailedRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.fail_ai_memory_job(
                user_id,
                request.worker_id,
                request.lease_token,
                request.failure_summary,
                request.now,
            )
        )

    @app.get(
        "/internal/game/activity-settings", response_model=ActivitySettingsResponse
    )
    def activity_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> ActivitySettingsResponse:
        return _activity_settings_response(repository.get_activity_settings())

    @app.get(
        "/internal/game/number-bomb/settings",
        response_model=NumberBombSettingsResponse,
    )
    def number_bomb_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> NumberBombSettingsResponse:
        settings = repository.get_number_bomb_settings()
        return NumberBombSettingsResponse(
            enabled=settings.enabled,
            signup_timeout_minutes=settings.signup_timeout_minutes,
            reminder_interval_seconds=settings.reminder_interval_seconds,
        )

    @app.get(
        "/internal/game/texas-holdem/settings",
        response_model=TexasHoldemSettingsResponse,
    )
    def texas_holdem_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> TexasHoldemSettingsResponse:
        return TexasHoldemSettingsResponse(
            **repository.get_texas_holdem_settings().__dict__
        )

    @app.patch(
        "/internal/game/texas-holdem/settings",
        response_model=TexasHoldemSettingsResponse,
    )
    def set_texas_holdem_settings(
        request: SetTexasHoldemSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> TexasHoldemSettingsResponse:
        settings = repository.set_texas_holdem_settings(
            **request.model_dump()
        )
        return TexasHoldemSettingsResponse(**settings.__dict__)

    @app.get(
        "/internal/game/dark-market/settings",
        response_model=DarkMarketSettingsResponse,
    )
    def dark_market_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> DarkMarketSettingsResponse:
        settings = repository.get_dark_market_settings()
        return DarkMarketSettingsResponse(
            enabled=settings.enabled,
            announcement_group_id=settings.announcement_group_id,
            duration_hours=settings.duration_hours,
            fee_percent=settings.fee_percent,
            version=settings.version,
            rank_limits=[
                DarkMarketRankLimitResponse(**item.__dict__)
                for item in settings.rank_limits
            ],
        )

    @app.patch(
        "/internal/game/dark-market/settings",
        response_model=DarkMarketSettingsResponse,
    )
    def set_dark_market_settings(
        request: SetDarkMarketSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> DarkMarketSettingsResponse:
        current = repository.get_dark_market_settings()
        if {item.rank_id for item in request.rank_limits} != {
            item.rank_id for item in current.rank_limits
        }:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "需要为每个职位配置上架次数",
            )
        try:
            settings = repository.set_dark_market_settings(
                enabled=request.enabled,
                announcement_group_id=request.announcement_group_id,
                duration_hours=request.duration_hours,
                fee_percent=request.fee_percent,
                rank_limits={
                    item.rank_id: item.daily_limit for item in request.rank_limits
                },
                expected_version=request.expected_version,
            )
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)
            ) from exc
        return DarkMarketSettingsResponse(
            enabled=settings.enabled,
            announcement_group_id=settings.announcement_group_id,
            duration_hours=settings.duration_hours,
            fee_percent=settings.fee_percent,
            version=settings.version,
            rank_limits=[
                DarkMarketRankLimitResponse(**item.__dict__)
                for item in settings.rank_limits
            ],
        )

    @app.get(
        "/internal/game/dark-market/listings",
        response_model=PaginatedDarkMarketListingsResponse,
    )
    def dark_market_listings(
        _: Annotated[None, Depends(authorize)],
        status_filter: Annotated[
            Literal["active", "sold", "unsold", "force_delisted"] | None,
            Query(alias="status"),
        ] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> PaginatedDarkMarketListingsResponse:
        items, total = repository.list_dark_market_listings(
            status_filter, page, page_size
        )
        return PaginatedDarkMarketListingsResponse(
            items=[DarkMarketListingResponse(**item.__dict__) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    @app.get(
        "/internal/game/dark-market/listings/{listing_id}",
        response_model=DarkMarketListingResponse,
    )
    def dark_market_listing(
        listing_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> DarkMarketListingResponse:
        item = repository.get_dark_market_listing(listing_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "暗网商品不存在")
        return DarkMarketListingResponse(
            **{
                **item.__dict__,
                "bids": [DarkMarketBidResponse(**bid.__dict__) for bid in item.bids],
            }
        )

    @app.post(
        "/internal/game/dark-market/listings/{listing_id}/force-delist",
        response_model=DarkMarketForceDelistResponse,
    )
    def force_delist_dark_market_listing(
        listing_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> DarkMarketForceDelistResponse:
        result = repository.force_delist_dark_market_listing(
            listing_id, clock()
        )
        if result.status == "not_found":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "暗网商品不存在")
        return DarkMarketForceDelistResponse(status=result.status)

    @app.patch(
        "/internal/game/number-bomb/settings",
        response_model=NumberBombSettingsResponse,
    )
    def set_number_bomb_settings(
        request: SetNumberBombSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> NumberBombSettingsResponse:
        settings = repository.set_number_bomb_settings(
            request.enabled,
            request.signup_timeout_minutes,
            request.reminder_interval_seconds,
        )
        return NumberBombSettingsResponse(
            enabled=settings.enabled,
            signup_timeout_minutes=settings.signup_timeout_minutes,
            reminder_interval_seconds=settings.reminder_interval_seconds,
        )

    @app.get(
        "/internal/game/red-packet/settings",
        response_model=RedPacketSettingsResponse,
    )
    def red_packet_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> RedPacketSettingsResponse:
        settings = repository.get_red_packet_settings()
        return RedPacketSettingsResponse(
            expiry_minutes=settings.expiry_minutes,
            empty_probability_percent=settings.empty_probability_percent,
        )

    @app.patch(
        "/internal/game/red-packet/settings",
        response_model=RedPacketSettingsResponse,
    )
    def set_red_packet_settings(
        request: SetRedPacketSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RedPacketSettingsResponse:
        settings = repository.set_red_packet_settings(
            request.expiry_minutes,
            request.empty_probability_percent,
        )
        return RedPacketSettingsResponse(
            expiry_minutes=settings.expiry_minutes,
            empty_probability_percent=settings.empty_probability_percent,
        )

    @app.get(
        "/internal/gameplay/current",
        response_model=GameplaySummariesResponse,
        response_model_exclude_unset=True,
    )
    def current_gameplay(
        _: Annotated[None, Depends(authorize)],
    ) -> GameplaySummariesResponse:
        items: list[GameplaySummaryResponse] = []
        for summary in repository.current_gameplay_admin_summaries(clock()):
            if summary.group_chat_id is None or summary.group_name is None:
                continue
            participants = []
            for participant in summary.participants:
                participant_values = {
                    "number": participant.number,
                    "display_name": participant.display_name,
                    "reported": participant.reported,
                }
                if summary.game_type == "texas_holdem":
                    participant_values.update(
                        state=participant.state,
                        stack=participant.stack,
                        street_contribution=participant.street_contribution,
                        total_contribution=participant.total_contribution,
                    )
                elif summary.game_type == "number_bomb":
                    participant_values.update(
                        state=participant.state,
                        total_points=participant.total_points,
                        retired_at_round=participant.retired_at_round,
                    )
                participants.append(GameplayParticipantResponse(**participant_values))
            values = {
                "group_chat_id": summary.group_chat_id,
                "group_name": summary.group_name,
                "game_type": summary.game_type,
                "game_id": summary.game_id,
                "state": summary.state,
                "participants": participants,
                "signup_deadline": summary.signup_deadline,
                "next_reminder_at": summary.next_reminder_at,
                "tipping_deadline": summary.tipping_deadline,
                "tip_total": summary.tip_total,
                "skip_enabled": summary.skip_enabled,
                "mode": summary.mode,
                "round_number": summary.round_number,
                "maximum_rounds": summary.maximum_rounds,
            }
            if summary.game_type == "texas_holdem":
                values.update(
                    button_seat=summary.button_seat,
                    current_seat=summary.current_seat,
                    board=list(summary.board),
                    pot=summary.pot,
                    action_deadline=summary.action_deadline,
                    to_call=summary.to_call,
                    legal_actions=list(summary.legal_actions),
                )
            items.append(GameplaySummaryResponse(**values))
        return GameplaySummariesResponse(items=items)

    @app.post(
        "/internal/gameplay/{group_chat_id}/{game_type}/{game_id}/force-end",
        response_model=AcceptedResponse,
    )
    def force_end_gameplay(
        group_chat_id: UUID,
        game_type: str,
        game_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        if not repository.force_end_gameplay(
            game_type, game_id, clock(), group_chat_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="gameplay identity is stale or mismatched",
            )
        return AcceptedResponse(accepted=True)

    @app.patch(
        "/internal/game/activity-settings", response_model=ActivitySettingsResponse
    )
    def set_activity_settings(
        request: SetActivitySettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> ActivitySettingsResponse:
        try:
            settings = repository.set_activity_settings(
                [
                    ActivityLevelRule(
                        rule.level, rule.character_threshold, rule.reward
                    )
                    for rule in request.rules
                ],
                request.report_times,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _activity_settings_response(settings)

    @app.get(
        "/internal/game/random-events/settings",
        response_model=RandomEventSettingsResponse,
    )
    def random_event_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventSettingsResponse:
        return _random_event_settings_response(repository.get_random_event_settings())

    @app.patch(
        "/internal/game/random-events/settings",
        response_model=RandomEventSettingsResponse,
    )
    def set_random_event_settings(
        request: SetRandomEventSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventSettingsResponse:
        try:
            settings = repository.set_random_event_settings(
                request.schedule_times,
                request.signup_notice_template,
                request.signup_timeout_minutes,
                request.reminder_interval_minutes,
                request.signup_allowed_commands,
                request.in_progress_allowed_commands,
                request.blocked_message,
                request.submission_enabled,
                request.submission_draft_timeout_minutes,
                request.submission_max_participants,
                request.submission_default_target_rounds,
                request.submission_default_event_reward,
                request.submission_approval_reward,
                request.tipping_duration_seconds,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _random_event_settings_response(settings)

    @app.get(
        "/internal/game/hide-and-seek/settings",
        response_model=HideAndSeekSettingsResponse,
    )
    def hide_and_seek_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> HideAndSeekSettingsResponse:
        return _hide_and_seek_settings_response(repository.get_hide_and_seek_settings())

    @app.patch(
        "/internal/game/hide-and-seek/settings",
        response_model=HideAndSeekSettingsResponse,
    )
    def set_hide_and_seek_settings(
        request: SetHideAndSeekSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> HideAndSeekSettingsResponse:
        try:
            settings = repository.set_hide_and_seek_settings(
                request.enabled,
                request.entry_fee,
                request.win_reward,
                request.daily_limit,
                request.selection_timeout_minutes,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _hide_and_seek_settings_response(settings)

    @app.get(
        "/internal/game/hide-and-seek/scenes",
        response_model=PaginatedHideAndSeekScenesResponse,
    )
    def hide_and_seek_scenes(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedHideAndSeekScenesResponse:
        scenes, total = repository.list_hide_and_seek_scenes_page(page, page_size)
        return PaginatedHideAndSeekScenesResponse(
            items=[_hide_and_seek_scene_response(scene) for scene in scenes],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.post(
        "/internal/game/hide-and-seek/scenes",
        response_model=HideAndSeekSceneResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_hide_and_seek_scene(
        request: CreateHideAndSeekSceneRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> HideAndSeekSceneResponse:
        try:
            scene = repository.create_hide_and_seek_scene(request.name)
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _hide_and_seek_scene_response(scene)

    @app.put(
        "/internal/game/hide-and-seek/scenes/{scene_id}",
        response_model=HideAndSeekSceneResponse,
    )
    def update_hide_and_seek_scene(
        scene_id: UUID,
        request: UpdateHideAndSeekSceneRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> HideAndSeekSceneResponse:
        try:
            scene = repository.update_hide_and_seek_scene(
                scene_id, request.name, request.enabled
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _hide_and_seek_scene_response(scene)

    @app.delete(
        "/internal/game/hide-and-seek/scenes/{scene_id}",
        response_model=AcceptedResponse,
    )
    def delete_hide_and_seek_scene(
        scene_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.delete_hide_and_seek_scene(scene_id))

    @app.get(
        "/internal/game/memory-assessment/settings",
        response_model=MemoryAssessmentSettingsResponse,
    )
    def memory_assessment_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> MemoryAssessmentSettingsResponse:
        return _memory_assessment_settings_response(repository)

    @app.patch(
        "/internal/game/memory-assessment/settings",
        response_model=MemoryAssessmentSettingsResponse,
    )
    def set_memory_assessment_settings(
        request: SetMemoryAssessmentSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> MemoryAssessmentSettingsResponse:
        try:
            repository.set_memory_assessment_settings(
                enabled=request.enabled,
                single_daily_limit=request.single_daily_limit,
                single_recall_seconds=request.single_recall_seconds,
                duel_recall_seconds=request.duel_recall_seconds,
                duel_difficulty_level=request.duel_difficulty_level,
                duel_base_pool=request.duel_base_pool,
                duel_wrong_freeze=request.duel_wrong_freeze,
                duel_wrong_limit=request.duel_wrong_limit,
                duel_answer_timeout_minutes=request.duel_answer_timeout_minutes,
                duel_signup_timeout_minutes=request.duel_signup_timeout_minutes,
                character_set=request.character_set,
                levels=[
                    MemoryAssessmentLevelRule(
                        level=rule.level,
                        answer_length=rule.answer_length,
                        reward=rule.reward,
                    )
                    for rule in request.levels
                ],
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _memory_assessment_settings_response(repository)

    @app.get(
        "/internal/game/undercover/settings",
        response_model=UndercoverSettingsResponse,
    )
    def undercover_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> UndercoverSettingsResponse:
        return _undercover_settings_response(repository)

    @app.patch(
        "/internal/game/undercover/settings",
        response_model=UndercoverSettingsResponse,
    )
    def set_undercover_settings(
        request: SetUndercoverSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> UndercoverSettingsResponse:
        try:
            repository.set_undercover_settings(
                request.enabled,
                request.vote_seconds,
                request.whiteboard_win_remaining,
                [
                    UndercoverRoleRule(
                        player_count=role.player_count,
                        civilian_count=role.civilian_count,
                        undercover_count=role.undercover_count,
                        whiteboard_count=role.whiteboard_count,
                    )
                    for role in request.roles
                ],
                signup_timeout_minutes=request.signup_timeout_minutes,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _undercover_settings_response(repository)

    @app.get(
        "/internal/game/undercover/session",
        response_model=UndercoverSessionResponse,
    )
    def undercover_session(
        _: Annotated[None, Depends(authorize)],
    ) -> UndercoverSessionResponse:
        summary = repository.undercover_session_summary()
        return UndercoverSessionResponse(
            state=summary.state,
            target_player_count=summary.target_player_count,
            player_count=summary.player_count,
            queued_count=summary.queued_count,
            current_vote_round=summary.current_vote_round,
            vote_deadline=summary.vote_deadline,
        )

    @app.get(
        "/internal/game/blame-bomb/settings",
        response_model=BlameGameSettingsResponse,
    )
    def blame_game_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> BlameGameSettingsResponse:
        return _blame_game_settings_response(repository)

    @app.patch(
        "/internal/game/blame-bomb/settings",
        response_model=BlameGameSettingsResponse,
    )
    def set_blame_game_settings(
        request: SetBlameGameSettingsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> BlameGameSettingsResponse:
        try:
            repository.set_blame_game_settings(
                request.enabled,
                request.signup_timeout_seconds,
                request.turn_timeout_seconds,
                [
                    (
                        duration.player_count,
                        duration.minimum_seconds,
                        duration.maximum_seconds,
                    )
                    for duration in request.durations
                ],
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _blame_game_settings_response(repository)

    @app.get(
        "/internal/game/blame-bomb/incidents",
        response_model=PaginatedBlameIncidentCardsResponse,
    )
    def blame_incident_cards(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedBlameIncidentCardsResponse:
        cards, total = repository.list_blame_incident_cards_page(page, page_size)
        return PaginatedBlameIncidentCardsResponse(
            items=[_blame_incident_card_response(card) for card in cards],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.post(
        "/internal/game/blame-bomb/incidents",
        response_model=BlameIncidentCardResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_blame_incident_card(
        request: CreateBlameIncidentCardRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> BlameIncidentCardResponse:
        try:
            card = repository.create_blame_incident_card(
                request.name, request.description, request.keywords
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _blame_incident_card_response(card)

    @app.put(
        "/internal/game/blame-bomb/incidents/{card_id}",
        response_model=BlameIncidentCardResponse,
    )
    def update_blame_incident_card(
        card_id: UUID,
        request: UpdateBlameIncidentCardRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> BlameIncidentCardResponse:
        try:
            card = repository.update_blame_incident_card(
                card_id,
                request.name,
                request.description,
                request.keywords,
                request.enabled,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _blame_incident_card_response(card)

    @app.delete(
        "/internal/game/blame-bomb/incidents/{card_id}",
        response_model=AcceptedResponse,
    )
    def delete_blame_incident_card(
        card_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.delete_blame_incident_card(card_id)
        )

    @app.get(
        "/internal/game/blame-bomb/session",
        response_model=BlameGameSessionResponse,
    )
    def blame_game_session(
        _: Annotated[None, Depends(authorize)],
    ) -> BlameGameSessionResponse:
        return _blame_game_session_response(repository, clock())

    @app.post(
        "/internal/game/blame-bomb/end",
        response_model=AcceptedResponse,
    )
    def end_blame_game(
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        result = repository.admin_end_blame_game(clock())
        return AcceptedResponse(
            accepted=result.status in {"cancelled", "settled", "signup_expired"}
        )

    @app.get(
        "/internal/random-event-submissions",
    )
    def random_event_submissions(
        _: Annotated[None, Depends(authorize)],
        status_filter: str | None = Query(None, alias="status"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        allowed = {
            "draft", "cancelled", "pending", "approved", "rejected",
            "withdrawn", "expired",
        }
        if status_filter is not None and status_filter not in allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "投稿状态无效")
        rows, total = repository.list_random_event_submissions(
            status_filter, page, page_size
        )
        return {
            "items": [
                _random_event_submission_response(submission, user)
                for submission, user in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        }

    @app.get("/internal/random-event-submissions/{submission_id}")
    def random_event_submission(
        submission_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        row = repository.random_event_submission_with_user(submission_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "投稿不存在")
        return _random_event_submission_response(*row)

    @app.patch("/internal/random-event-submissions/{submission_id}")
    def update_random_event_submission(
        submission_id: UUID,
        request: dict,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        try:
            repository.update_random_event_submission_content(
                submission_id,
                request["content"],
                datetime.fromisoformat(str(request["now"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        row = repository.random_event_submission_with_user(submission_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "投稿不存在")
        return _random_event_submission_response(*row)

    @app.post("/internal/random-event-submissions/{submission_id}/approve")
    def approve_random_event_submission(
        submission_id: UUID,
        request: dict,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        try:
            repository.approve_random_event_submission(
                submission_id,
                str(request.get("reviewer", "")),
                datetime.fromisoformat(str(request["now"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        row = repository.random_event_submission_with_user(submission_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "投稿不存在")
        return _random_event_submission_response(*row)

    @app.post("/internal/random-event-submissions/{submission_id}/reject")
    def reject_random_event_submission(
        submission_id: UUID,
        request: dict,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        try:
            repository.reject_random_event_submission(
                submission_id,
                str(request.get("reviewer", "")),
                str(request.get("reason", "")),
                datetime.fromisoformat(str(request["now"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        row = repository.random_event_submission_with_user(submission_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "投稿不存在")
        return _random_event_submission_response(*row)

    @app.get(
        "/internal/game/random-events/scenes",
        response_model=PaginatedRandomEventScenesResponse,
    )
    def random_event_scenes(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> PaginatedRandomEventScenesResponse:
        scenes, total = repository.list_random_event_scenes_page(page, page_size)
        return PaginatedRandomEventScenesResponse(
            items=[_random_event_scene_response(scene) for scene in scenes],
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
        )

    @app.post(
        "/internal/game/random-events/scenes",
        response_model=RandomEventSceneResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_random_event_scene(
        request: CreateRandomEventSceneRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventSceneResponse:
        try:
            scene = repository.create_random_event_scene(
                request.name,
                request.signup_text,
                [event.model_dump() for event in request.events] or request.openings,
                request.reward,
                request.target_rounds,
                [(seat.role, seat.capacity) for seat in request.seats],
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _random_event_scene_response(scene)

    @app.put(
        "/internal/game/random-events/scenes/{scene_id}",
        response_model=RandomEventSceneResponse,
    )
    def update_random_event_scene(
        scene_id: UUID,
        request: UpdateRandomEventSceneRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventSceneResponse:
        try:
            scene = repository.update_random_event_scene(
                scene_id,
                request.name,
                request.signup_text,
                [event.model_dump() for event in request.events] or request.openings,
                request.reward,
                request.target_rounds,
                [(seat.role, seat.capacity) for seat in request.seats],
                request.enabled,
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _random_event_scene_response(scene)

    @app.delete(
        "/internal/game/random-events/scenes/{scene_id}",
        response_model=AcceptedResponse,
    )
    def delete_random_event_scene(
        scene_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.delete_random_event_scene(scene_id))

    @app.get(
        "/internal/game/random-events/today",
        response_model=list[RandomEventScheduleResponse],
    )
    def today_random_event_schedules(
        _: Annotated[None, Depends(authorize)],
    ) -> list[RandomEventScheduleResponse]:
        return [
            _random_event_schedule_response(schedule)
            for schedule in repository.list_today_random_event_schedules(clock())
        ]

    @app.patch(
        "/internal/game/random-events/today/{schedule_id}",
        response_model=RandomEventScheduleResponse,
    )
    def reschedule_random_event(
        schedule_id: UUID,
        request: RescheduleRandomEventRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventScheduleResponse:
        try:
            schedule = repository.reschedule_random_event(
                schedule_id, request.scheduled_at, clock()
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))
        return _random_event_schedule_response(schedule)

    @app.post(
        "/internal/game/random-events/today",
        response_model=RandomEventScheduleResponse,
    )
    def create_today_random_event(
        request: CreateTodayRandomEventRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventScheduleResponse:
        try:
            return _random_event_schedule_response(
                repository.create_today_random_event(
                    request.scene_id,
                    request.event_name,
                    request.scheduled_at,
                    clock(),
                    request.group_chat_id,
                )
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))

    @app.delete(
        "/internal/game/random-events/today/{schedule_id}",
        response_model=AcceptedResponse,
    )
    def delete_today_random_event(
        schedule_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(
            accepted=repository.delete_today_random_event(schedule_id, clock())
        )

    @app.post(
        "/internal/game/random-events/today/{schedule_id}/trigger",
        response_model=RandomEventScheduleResponse,
    )
    def trigger_random_event(
        schedule_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventScheduleResponse:
        try:
            return _random_event_schedule_response(
                repository.trigger_random_event(schedule_id, clock())
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))

    @app.get(
        "/internal/game/random-events/today/{schedule_id}/details",
        response_model=RandomEventDetailsResponse,
    )
    def random_event_details(
        schedule_id: UUID,
        _: Annotated[None, Depends(authorize)],
    ) -> RandomEventDetailsResponse:
        try:
            return RandomEventDetailsResponse(
                items=[
                    {"display_name": name, "content": content, "occurred_at": occurred_at}
                    for name, content, occurred_at in repository.list_random_event_details(schedule_id)
                ],
                tips=[
                    {
                        "sender_display_name": sender,
                        "recipient_display_name": recipient,
                        "amount": amount,
                        "created_at": created_at,
                    }
                    for sender, recipient, amount, created_at in repository.list_random_event_tips(schedule_id)
                ],
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error))

    @app.post("/internal/daily-jobs/run", response_model=AcceptedResponse)
    def run_daily_jobs(
        request: DailyJobsRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        repository.run_daily_jobs(request.now)
        return AcceptedResponse(accepted=True)

    @app.get(
        "/internal/admin/login/lease",
        response_model=ManualLoginLeaseResponse | None,
    )
    def manual_login_lease(
        _: Annotated[None, Depends(authorize)],
    ) -> ManualLoginLeaseResponse | None:
        lease = repository.manual_login_lease(clock())
        return None if lease is None else _manual_login_lease_response(lease)

    @app.post(
        "/internal/admin/login/start", response_model=ManualLoginLeaseResponse
    )
    def start_manual_login(
        request: ManualLoginActorRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> ManualLoginLeaseResponse:
        try:
            lease = repository.start_manual_login(
                request.operator_id, request.operator_name, clock()
            )
        except ManualLoginBusyError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        return _manual_login_lease_response(lease)

    @app.post(
        "/internal/admin/login/finish", response_model=AcceptedResponse
    )
    def finish_manual_login(
        request: ManualLoginActorRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        try:
            repository.finish_manual_login(request.operator_id, clock())
        except ManualLoginOwnerError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        return AcceptedResponse(accepted=True)

    @app.post(
        "/internal/admin/login/cancel", response_model=AcceptedResponse
    )
    def cancel_manual_login(
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        return AcceptedResponse(accepted=repository.cancel_manual_login(clock()))

    @app.post("/internal/worker-commands", response_model=WorkerCommandResponse)
    def enqueue_worker_command(
        request: WorkerCommandRequest, _: Annotated[None, Depends(authorize)]
    ) -> WorkerCommandResponse:
        return _worker_command_response(
            repository.enqueue_worker_command(request.command)
        )

    @app.post(
        "/internal/worker-commands/claim",
        response_model=WorkerCommandResponse | None,
    )
    def claim_worker_command(
        request: ClaimRequest, _: Annotated[None, Depends(authorize)]
    ) -> WorkerCommandResponse | None:
        record = repository.claim_worker_command(
            request.worker_id, request.now, request.lease_seconds
        )
        return None if record is None else _worker_command_response(record)

    @app.post(
        "/internal/worker-commands/{command_id}/complete",
        response_model=AcceptedResponse,
    )
    def complete_worker_command(
        command_id: UUID,
        request: CompleteWorkerCommandRequest,
        _: Annotated[None, Depends(authorize)],
    ) -> AcceptedResponse:
        accepted = repository.complete_worker_command(
            command_id,
            request.worker_id,
            request.lease_token,
            request.status,
            request.now,
        )
        return AcceptedResponse(accepted=accepted)

    @app.get("/healthz", response_model=HealthResponse)
    def health(response: Response) -> HealthResponse:
        try:
            record = _latest_heartbeat(repository)
            bootstrap_ready = (
                not require_group_chat_bootstrap
                or repository.group_chat_bootstrap_ready()
            )
        except SQLAlchemyError:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return HealthResponse(
                database_available=False,
                latest_worker_heartbeat_age_seconds=None,
            )
        if not bootstrap_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        age = None
        if record is not None:
            age = max(0.0, (clock() - record.recorded_at).total_seconds())
        return HealthResponse(
            database_available=True,
            latest_worker_heartbeat_age_seconds=age,
        )

    return app


def _ensure_primary_group(
    repository: CoreRepository, chat_url: str | None
) -> bool:
    try:
        if repository.group_chat_bootstrap_ready():
            return True
        if chat_url is None:
            return False
        repository.bootstrap_primary_group(chat_url, beijing_now())
        return repository.group_chat_bootstrap_ready()
    except (SQLAlchemyError, ValueError):
        return False


def _group_chat_response(group, runtime) -> GroupChatResponse:
    return GroupChatResponse(
        id=group.id,
        name=group.name,
        chat_url=group.chat_url,
        chatroom_id=group.chatroom_id,
        listening_enabled=group.listening_enabled,
        games_enabled=group.games_enabled,
        enabled_game_types=list(group.enabled_game_types),
        random_events_enabled=group.random_events_enabled,
        announcements_enabled=group.announcements_enabled,
        adult_shop_enabled=group.adult_shop_enabled,
        performances_enabled=group.performances_enabled,
        created_at=group.created_at,
        updated_at=group.updated_at,
        deleted_at=group.deleted_at,
        runtime=None
        if runtime is None
        else GroupChatRuntimeResponse(
            connection_state=runtime.connection_state,
            last_connected_at=runtime.last_connected_at,
            last_inbound_at=runtime.last_inbound_at,
            last_outbound_at=runtime.last_outbound_at,
            last_error_summary=runtime.last_error_summary,
            worker_id=runtime.worker_id,
            updated_at=runtime.updated_at,
        ),
    )


def _performance_response(view) -> PerformanceResponse:
    return PerformanceResponse(
        id=view.id,
        owner_platform_id=view.owner_platform_id,
        owner_display_name=view.owner_display_name,
        group_chat_id=view.group_chat_id,
        title=view.title,
        introduction=view.introduction,
        scheduled_at=view.scheduled_at,
        event_date=view.event_date,
        participant_names=list(view.participant_names),
        cover_url=view.cover_url,
        cover_alt=view.cover_alt,
        state=view.state,
        pre_notice_sent_at=view.pre_notice_sent_at,
        tipping_deadline=view.tipping_deadline,
        reviewed_by=view.reviewed_by,
        reviewed_at=view.reviewed_at,
        rejection_reason=view.rejection_reason,
        cancellation_reason=view.cancellation_reason,
        cancelled_at=view.cancelled_at,
        started_at=view.started_at,
        ended_at=view.ended_at,
        tips=[
            PerformanceTipResponse(
                sender_display_name=tip.sender_display_name,
                recipient_display_name=tip.recipient_display_name,
                amount=tip.amount,
                created_at=tip.created_at,
            )
            for tip in view.tips
        ],
        audit_events=[
            PerformanceAuditResponse(
                event_type=event.event_type,
                actor=event.actor,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in view.audit_events
        ],
        extension=None
        if view.extension is None
        else PerformanceExtensionResponse(
            id=view.extension.id,
            reservation_id=view.extension.reservation_id,
            duration_minutes=view.extension.duration_minutes,
            original_scheduled_at=view.extension.original_scheduled_at,
            proposed_scheduled_at=view.extension.proposed_scheduled_at,
            state=view.extension.state,
            rejection_reason=view.extension.rejection_reason,
            requested_at=view.extension.requested_at,
            reviewed_at=view.extension.reviewed_at,
        ),
    )


def _latest_heartbeat(repository: CoreRepository) -> WorkerInstanceRecord | None:
    with repository._session() as session:
        return session.scalar(
            select(WorkerInstanceRecord)
            .order_by(WorkerInstanceRecord.recorded_at.desc())
            .limit(1)
        )


def _heartbeat_response(record: WorkerInstanceRecord) -> HeartbeatResponse:
    return HeartbeatResponse(
        worker_id=record.worker_id,
        login_state=record.login_state,
        recorded_at=record.recorded_at,
        listening=record.listening,
        listening_desired=record.listening_desired,
        bot_delivery_state=record.bot_delivery_state,
        bot_delivery_error=record.bot_delivery_error,
    )


def _manual_login_lease_response(lease: ManualLoginLease) -> ManualLoginLeaseResponse:
    return ManualLoginLeaseResponse(
        operator_id=lease.operator_id,
        operator_name=lease.operator_name,
        expires_at=lease.expires_at,
    )


def _worker_command_response(record: WorkerCommandRecord) -> WorkerCommandResponse:
    return WorkerCommandResponse(
        id=record.id,
        command=record.command,
        status=record.status,
        lease_token=record.lease_token,
        lease_expires_at=record.lease_expires_at,
    )


def _item_response(record) -> ItemResponse:
    return ItemResponse(
        public_number=record.public_number,
        name=record.name,
        description=record.description,
        price=record.price,
        stock=record.stock,
        unlimited_stock=record.unlimited_stock,
        system_key=record.system_key,
        effect_type=record.effect_type,
        minimum_rank_order=record.minimum_rank_order,
        enabled=record.enabled,
    )


def _rank_response(record) -> RankResponse:
    return RankResponse(
        id=record.id,
        sort_order=record.sort_order,
        name=record.name,
        level_label=record.level_label,
        promotion_price=record.promotion_price,
        vote_weight=record.vote_weight,
        multiplayer_game_limit=record.multiplayer_game_limit,
        has_group_management=record.has_group_management,
        is_board=record.is_board,
        enabled=record.enabled,
    )


def _department_response(record) -> DepartmentResponse:
    return DepartmentResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        is_default=record.is_default,
        enabled=record.enabled,
    )


def _user_response(profile) -> UserResponse:
    if profile is None:
        raise RuntimeError("employee profile is missing")
    return UserResponse(
        platform_id=profile.user.platform_id,
        display_name=profile.user.display_name,
        employee_number=profile.user.employee_number,
        balance=profile.user.balance,
        joined_at=profile.user.joined_at,
        rank_name=profile.rank.name,
        rank_level_label=profile.rank.level_label,
        department_name=profile.department.name,
    )


def _user_profile_response(profile) -> UserProfileResponse:
    return UserProfileResponse(
        platform_id=profile.user.platform_id,
        display_name=profile.user.display_name,
        balance=profile.user.balance,
        rank=_rank_response(profile.rank),
        department=_department_response(profile.department),
    )


def _promotion_request_response(record) -> PromotionRequestResponse:
    return PromotionRequestResponse(
        number=record.number,
        applicant_platform_id=record.applicant_platform_id,
        applicant_name=record.applicant_name,
        source_rank_name=record.source_rank_name,
        target_rank_name=record.target_rank_name,
        price=record.price,
        state=record.state,
        requested_at=record.requested_at,
        expires_at=record.expires_at,
        decided_at=record.decided_at,
    )


def _department_request_response(record) -> DepartmentRequestResponse:
    return DepartmentRequestResponse(
        number=record.number,
        applicant_platform_id=record.applicant_platform_id,
        applicant_name=record.applicant_name,
        source_department_name=record.source_department_name,
        target_department_name=record.target_department_name,
        state=record.state,
        requested_at=record.requested_at,
        expires_at=record.expires_at,
        decided_at=record.decided_at,
        approver_name=record.approver_name,
        decision=record.decision,
    )


def _game_settings_response(record) -> GameSettingsResponse:
    return GameSettingsResponse(
        currency_name=record.currency_name,
        onboarding_bonus=record.onboarding_bonus,
        checkin_reward=record.checkin_reward,
        weekly_attendance_reward=record.weekly_attendance_reward,
    )


def _ai_assistant_settings_response(
    repository: CoreRepository,
) -> AIAssistantSettingsResponse:
    settings, quotas = repository.get_ai_assistant_configuration()
    memory = repository.get_ai_memory_settings()
    return AIAssistantSettingsResponse(
        enabled=settings.enabled,
        trigger_prefixes=list(settings.trigger_prefixes),
        persona=settings.persona,
        system_prompt=settings.system_prompt,
        over_limit_reply=settings.over_limit_reply,
        failure_reply=settings.failure_reply,
        max_response_chars=settings.max_response_chars,
        timeout_seconds=settings.timeout_seconds,
        memory_enabled=memory.enabled,
        extraction_prompt=memory.extraction_prompt,
        history_limit=memory.history_limit,
        max_memory_chars=memory.max_memory_chars,
        batch_message_threshold=memory.batch_message_threshold,
        max_entries_per_category=memory.max_entries_per_category,
        candidate_expiry_days=memory.candidate_expiry_days,
        quotas=[
            AIRankQuotaResponse(
                rank_id=quota.rank_id,
                rank_name=quota.rank_name,
                rank_level_label=quota.rank_level_label,
                daily_limit=quota.daily_limit,
            )
            for quota in quotas
        ],
    )


def _ai_player_impression_response(record) -> AIPlayerImpressionResponse:
    return AIPlayerImpressionResponse(
        id=record.id,
        category=record.category,
        content=record.content,
        source=record.source,
        pinned=record.pinned,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _ai_knowledge_card_response(record) -> AIKnowledgeCardResponse:
    return AIKnowledgeCardResponse(
        id=record.id,
        topic=record.topic,
        title=record.title,
        keywords=list(record.keywords),
        content=record.content,
        enabled=record.enabled,
        priority=record.priority,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _ai_player_memory_response(
    repository: CoreRepository, platform_id: str
) -> AIPlayerMemoryResponse:
    result = repository.get_ai_player_memory(platform_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    user, memory = result
    impressions = repository.list_ai_player_impressions(platform_id)
    facts = repository.list_ai_activity_facts(platform_id)
    updated_candidates = [entry.updated_at for entry in impressions]
    if memory is not None:
        updated_candidates.append(memory.updated_at)
    return AIPlayerMemoryResponse(
        platform_id=user.platform_id,
        display_name=user.display_name,
        impressions=[_ai_player_impression_response(entry) for entry in impressions],
        activity_facts=[
            AIActivityFactResponse(
                activity_type=fact.activity_type,
                participation_count=fact.participation_count,
                win_count=fact.win_count,
                loss_count=fact.loss_count,
                last_result=fact.last_result,
                last_result_at=fact.last_result_at,
            )
            for fact in facts
        ],
        legacy_memory_text=memory.memory_text if memory is not None else "",
        updated_at=max(updated_candidates) if updated_candidates else None,
    )


def _activity_settings_response(settings) -> ActivitySettingsResponse:
    return ActivitySettingsResponse(
        rules=[
            ActivityLevelRuleModel(
                level=rule.level,
                character_threshold=rule.character_threshold,
                reward=rule.reward,
            )
            for rule in settings.rules
        ],
        report_times=settings.report_times,
    )


def _random_event_settings_response(settings) -> RandomEventSettingsResponse:
    return RandomEventSettingsResponse(
        schedule_times=settings.schedule_times,
        signup_notice_template=settings.signup_notice_template,
        signup_timeout_minutes=settings.signup_timeout_minutes,
        reminder_interval_minutes=settings.reminder_interval_minutes,
        signup_allowed_commands=settings.signup_allowed_commands,
        in_progress_allowed_commands=settings.in_progress_allowed_commands,
        blocked_message=settings.blocked_message,
        submission_enabled=settings.submission_enabled,
        submission_draft_timeout_minutes=settings.submission_draft_timeout_minutes,
        submission_max_participants=settings.submission_max_participants,
        submission_default_target_rounds=settings.submission_default_target_rounds,
        submission_default_event_reward=settings.submission_default_event_reward,
        submission_approval_reward=settings.submission_approval_reward,
        tipping_duration_seconds=settings.tipping_duration_seconds,
    )


def _hide_and_seek_settings_response(settings) -> HideAndSeekSettingsResponse:
    return HideAndSeekSettingsResponse(
        enabled=settings.enabled,
        entry_fee=settings.entry_fee,
        win_reward=settings.win_reward,
        daily_limit=settings.daily_limit,
        selection_timeout_minutes=settings.selection_timeout_minutes,
    )


def _hide_and_seek_scene_response(scene) -> HideAndSeekSceneResponse:
    return HideAndSeekSceneResponse(id=scene.id, name=scene.name, enabled=scene.enabled)


def _memory_assessment_settings_response(
    repository: CoreRepository,
) -> MemoryAssessmentSettingsResponse:
    settings = repository.get_memory_assessment_settings()
    return MemoryAssessmentSettingsResponse(
        enabled=settings.enabled,
        single_daily_limit=settings.single_daily_limit,
        single_recall_seconds=settings.single_recall_seconds,
        duel_recall_seconds=settings.duel_recall_seconds,
        duel_difficulty_level=settings.duel_difficulty_level,
        duel_base_pool=settings.duel_base_pool,
        duel_wrong_freeze=settings.duel_wrong_freeze,
        duel_wrong_limit=settings.duel_wrong_limit,
        duel_answer_timeout_minutes=settings.duel_answer_timeout_minutes,
        duel_signup_timeout_minutes=settings.duel_signup_timeout_minutes,
        character_set=settings.character_set,
        levels=[
            MemoryAssessmentLevelRuleModel(
                level=rule.level,
                answer_length=rule.answer_length,
                reward=rule.reward,
            )
            for rule in repository.list_memory_assessment_levels()
        ],
    )


def _undercover_settings_response(repository: CoreRepository) -> UndercoverSettingsResponse:
    settings = repository.get_undercover_settings()
    return UndercoverSettingsResponse(
        enabled=settings.enabled,
        vote_seconds=settings.vote_seconds,
        whiteboard_win_remaining=settings.whiteboard_win_remaining,
        signup_timeout_minutes=settings.signup_timeout_minutes,
        roles=[
            UndercoverRoleRuleModel(
                player_count=rule.player_count,
                civilian_count=rule.civilian_count,
                undercover_count=rule.undercover_count,
                whiteboard_count=rule.whiteboard_count,
            )
            for rule in repository.list_undercover_role_rules()
        ],
    )


def _blame_game_settings_response(
    repository: CoreRepository,
) -> BlameGameSettingsResponse:
    settings = repository.get_blame_game_settings()
    return BlameGameSettingsResponse(
        enabled=settings.enabled,
        signup_timeout_seconds=settings.signup_timeout_seconds,
        turn_timeout_seconds=settings.turn_timeout_seconds,
        durations=[
            BlameGameDurationRuleModel(
                player_count=duration.player_count,
                minimum_seconds=duration.minimum_seconds,
                maximum_seconds=duration.maximum_seconds,
            )
            for duration in settings.durations
        ],
    )


def _blame_incident_card_response(card) -> BlameIncidentCardResponse:
    return BlameIncidentCardResponse(
        id=card.id,
        name=card.name,
        description=card.description,
        keywords=list(card.keywords),
        enabled=card.enabled,
    )


def _blame_game_session_response(
    repository: CoreRepository,
    now: datetime,
) -> BlameGameSessionResponse:
    summary = repository.blame_game_summary(now)
    holder = next(
        (
            player
            for player in summary.players
            if player.seat_number == summary.current_holder_number
        ),
        None,
    )
    incident = None
    if summary.incident_name is not None and summary.incident_description is not None:
        incident = BlameGameIncidentResponse(
            name=summary.incident_name,
            description=summary.incident_description,
            keywords=list(summary.incident_keywords),
        )
    return BlameGameSessionResponse(
        state=summary.state,
        target_player_count=summary.target_player_count,
        players=[
            BlameGamePlayerResponse(
                display_name=player.display_name,
                seat_number=player.seat_number,
                state=player.state,
            )
            for player in summary.players
        ],
        incident=incident,
        current_holder=(
            None
            if holder is None or holder.seat_number is None
            else BlameGameHolderResponse(
                display_name=holder.display_name,
                seat_number=holder.seat_number,
            )
        ),
        temperature=summary.temperature,
    )


def _random_event_scene_response(scene) -> RandomEventSceneResponse:
    return RandomEventSceneResponse(
        id=scene.id,
        name=scene.name,
        signup_text=scene.signup_text,
        openings=scene.openings,
        events=[{"name": event.name, "opening_text": event.opening_text} for event in scene.events],
        reward=scene.reward,
        target_rounds=scene.target_rounds,
        enabled=scene.enabled,
        seats=[{"role": seat.role, "capacity": seat.capacity} for seat in scene.seats],
    )


def _random_event_submission_response(submission, user) -> dict:
    return {
        "id": submission.id,
        "number": submission.number,
        "status": submission.status,
        "current_step": submission.current_step,
        "content": submission.content,
        "target_rounds": submission.target_rounds,
        "event_reward": submission.event_reward,
        "approval_reward": submission.approval_reward,
        "created_at": submission.created_at,
        "updated_at": submission.updated_at,
        "submitted_at": submission.submitted_at,
        "reviewer": submission.reviewer,
        "reviewed_at": submission.reviewed_at,
        "rejection_reason": submission.rejection_reason,
        "scene_id": submission.scene_id,
        "reward_granted_at": submission.reward_granted_at,
        "platform_id": user.platform_id,
        "display_name": user.display_name,
        "employee_number": format_employee_number(user.employee_number),
    }


def _random_event_schedule_response(schedule) -> RandomEventScheduleResponse:
    return RandomEventScheduleResponse(
        id=schedule.id,
        group_chat_id=schedule.group_chat_id,
        event_date=schedule.event_date,
        scheduled_at=schedule.scheduled_at,
        status=schedule.status,
        scene_name=schedule.scene_name,
        event_name=schedule.event_name,
        is_cross_day=schedule.is_cross_day,
    )


def _template_response(definition, record) -> CommandTemplateResponse:
    return CommandTemplateResponse(
        scenario=definition.scenario,
        label=definition.label,
        template=definition.default if record is None else record.template,
        variables=list(definition.variables),
    )
