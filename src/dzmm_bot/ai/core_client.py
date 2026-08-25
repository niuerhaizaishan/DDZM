from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import httpx

from .impressions import AIImpressionOperation


@dataclass(frozen=True)
class AIConversationMessage:
    role: str
    content: str


@dataclass(frozen=True)
class AIClaim:
    id: UUID
    lease_token: UUID
    system_prompt: str
    history_messages: tuple[AIConversationMessage, ...]
    user_content: str
    max_response_chars: int
    timeout_seconds: int


@dataclass(frozen=True)
class ShopSceneClaim:
    id: UUID
    lease_token: UUID
    system_prompt: str
    user_content: str
    max_response_chars: int
    timeout_seconds: int


@dataclass(frozen=True)
class AIMemoryClaim:
    user_id: UUID
    target_message_id: UUID
    lease_token: UUID
    extraction_prompt: str
    max_memory_chars: int
    stable_entries: tuple["AIImpressionEntry", ...]
    candidates: tuple["AIImpressionCandidate", ...]
    source_messages: tuple[str, ...]
    source_message_count: int


@dataclass(frozen=True)
class AIImpressionEntry:
    id: UUID
    category: str
    content: str
    pinned: bool


@dataclass(frozen=True)
class AIImpressionCandidate:
    id: UUID
    category: str
    content: str
    support_batches: int
    conflict_entry_id: UUID | None


class AICorePort(Protocol):
    def claim_shop_scene_job(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> ShopSceneClaim | None: ...

    def complete_shop_scene_job(
        self, job_id: UUID, worker_id: str, lease_token: UUID, text: str, now: datetime
    ) -> None: ...

    def fail_shop_scene_job(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        failure_summary: str,
        now: datetime,
    ) -> None: ...

    def claim_ai_request(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> AIClaim | None: ...

    def complete_ai_request(
        self,
        request_id: UUID,
        worker_id: str,
        lease_token: UUID,
        text: str,
        now: datetime,
    ) -> None: ...

    def fail_ai_request(
        self,
        request_id: UUID,
        worker_id: str,
        lease_token: UUID,
        failure_summary: str,
        now: datetime,
    ) -> None: ...

    def claim_ai_memory_job(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> AIMemoryClaim | None: ...

    def complete_ai_memory_job(
        self,
        user_id: UUID,
        worker_id: str,
        lease_token: UUID,
        target_message_id: UUID,
        operations: tuple[AIImpressionOperation, ...],
        source_message_count: int,
        now: datetime,
    ) -> None: ...

    def fail_ai_memory_job(
        self,
        user_id: UUID,
        worker_id: str,
        lease_token: UUID,
        failure_summary: str,
        now: datetime,
    ) -> None: ...


class AICoreClient:
    def __init__(
        self, base_url: str, token: str, *, client: httpx.Client | None = None
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"X-Core-Token": token},
            timeout=10,
        )

    def claim_ai_request(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> AIClaim | None:
        data = self._post(
            "/internal/ai/claim",
            {
                "worker_id": worker_id,
                "now": now.isoformat(),
                "lease_seconds": lease_seconds,
            },
        )
        if data is None:
            return None
        return AIClaim(
            id=UUID(data["id"]),
            lease_token=UUID(data["lease_token"]),
            system_prompt=data["system_prompt"],
            history_messages=tuple(
                AIConversationMessage(
                    role=item["role"],
                    content=item["content"],
                )
                for item in data.get("history_messages", [])
            ),
            user_content=data["user_content"],
            max_response_chars=data["max_response_chars"],
            timeout_seconds=data["timeout_seconds"],
        )

    def claim_shop_scene_job(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> ShopSceneClaim | None:
        data = self._post(
            "/internal/ai/shop-scenes/claim",
            {
                "worker_id": worker_id,
                "now": now.isoformat(),
                "lease_seconds": lease_seconds,
            },
        )
        if data is None:
            return None
        return ShopSceneClaim(
            id=UUID(data["id"]),
            lease_token=UUID(data["lease_token"]),
            system_prompt=data["system_prompt"],
            user_content=data["user_content"],
            max_response_chars=data["max_response_chars"],
            timeout_seconds=data["timeout_seconds"],
        )

    def complete_shop_scene_job(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        text: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/ai/shop-scenes/{job_id}/completed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "text": text,
                "now": now.isoformat(),
            },
        )

    def fail_shop_scene_job(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        failure_summary: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/ai/shop-scenes/{job_id}/failed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "failure_summary": failure_summary,
                "now": now.isoformat(),
            },
        )

    def complete_ai_request(
        self,
        request_id: UUID,
        worker_id: str,
        lease_token: UUID,
        text: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/ai/{request_id}/completed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "text": text,
                "now": now.isoformat(),
            },
        )

    def fail_ai_request(
        self,
        request_id: UUID,
        worker_id: str,
        lease_token: UUID,
        failure_summary: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/ai/{request_id}/failed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "failure_summary": failure_summary,
                "now": now.isoformat(),
            },
        )

    def claim_ai_memory_job(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> AIMemoryClaim | None:
        data = self._post(
            "/internal/ai/memory/claim",
            {
                "worker_id": worker_id,
                "now": now.isoformat(),
                "lease_seconds": lease_seconds,
            },
        )
        if data is None:
            return None
        return AIMemoryClaim(
            user_id=UUID(data["user_id"]),
            target_message_id=UUID(data["target_message_id"]),
            lease_token=UUID(data["lease_token"]),
            extraction_prompt=data["extraction_prompt"],
            max_memory_chars=data["max_memory_chars"],
            stable_entries=tuple(
                AIImpressionEntry(
                    id=UUID(item["id"]),
                    category=item["category"],
                    content=item["content"],
                    pinned=item["pinned"],
                )
                for item in data["stable_entries"]
            ),
            candidates=tuple(
                AIImpressionCandidate(
                    id=UUID(item["id"]),
                    category=item["category"],
                    content=item["content"],
                    support_batches=item["support_batches"],
                    conflict_entry_id=(
                        UUID(item["conflict_entry_id"])
                        if item["conflict_entry_id"] is not None
                        else None
                    ),
                )
                for item in data["candidates"]
            ),
            source_messages=tuple(data["source_messages"]),
            source_message_count=data["source_message_count"],
        )

    def complete_ai_memory_job(
        self,
        user_id: UUID,
        worker_id: str,
        lease_token: UUID,
        target_message_id: UUID,
        operations: tuple[AIImpressionOperation, ...],
        source_message_count: int,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/ai/memory/{user_id}/completed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "target_message_id": str(target_message_id),
                "operations": [_impression_operation_payload(item) for item in operations],
                "source_message_count": source_message_count,
                "now": now.isoformat(),
            },
        )

    def fail_ai_memory_job(
        self,
        user_id: UUID,
        worker_id: str,
        lease_token: UUID,
        failure_summary: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/ai/memory/{user_id}/failed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "failure_summary": failure_summary,
                "now": now.isoformat(),
            },
        )

    def _post(self, path: str, payload: dict):
        response = self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()


def _impression_operation_payload(operation: AIImpressionOperation) -> dict:
    payload = {"action": operation.action}
    for name in ("category", "content", "candidate_id", "entry_id"):
        value = getattr(operation, name)
        if value is not None:
            payload[name] = str(value) if isinstance(value, UUID) else value
    return payload
