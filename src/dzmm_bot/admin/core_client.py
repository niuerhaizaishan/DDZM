from typing import Callable, Protocol

import httpx
import websockets


class AdminCorePort(Protocol):
    def status(self) -> dict: ...

    def list_group_chats(self, include_deleted: bool = False) -> list[dict]: ...

    def create_group_chat(self, group: dict) -> dict: ...

    def update_group_chat(self, group_id: str, group: dict) -> dict: ...

    def delete_group_chat(self, group_id: str, now: str) -> dict: ...

    def login_state(self) -> str | None: ...

    def get_manual_login_lease(self) -> dict | None: ...

    def start_manual_login(self, operator_id: str, operator_name: str) -> dict: ...

    def finish_manual_login(self, operator_id: str, operator_name: str) -> dict: ...

    def cancel_manual_login(self) -> dict: ...

    def enqueue_command(self, command: str) -> dict: ...

    def list_game_commands(self) -> list[dict]: ...

    def set_game_command_enabled(self, command: str, enabled: bool) -> dict: ...

    def set_game_command_template(
        self, command: str, scenario: str, template: str
    ) -> dict: ...

    def list_game_users(self, page: int, page_size: int) -> dict: ...

    def list_balance_transactions(
        self, platform_id: str, page: int, page_size: int
    ) -> dict: ...

    def list_employee_group_messages(
        self,
        platform_id: str,
        page: int,
        page_size: int,
        group_chat_id: str | None = None,
    ) -> dict: ...

    def list_game_items(self, page: int, page_size: int) -> dict: ...

    def create_game_item(self, item: dict) -> dict: ...

    def list_ranks(self) -> list[dict]: ...

    def update_rank(self, rank_id: str, rank: dict) -> dict: ...

    def list_departments(self, page: int, page_size: int) -> dict: ...

    def create_department(self, department: dict) -> dict: ...

    def update_department(self, department_id: str, department: dict) -> dict: ...

    def delete_department(self, department_id: str) -> dict: ...

    def list_promotions(self, state: str | None, page: int, page_size: int) -> dict: ...

    def list_department_requests(
        self, state: str | None, page: int, page_size: int
    ) -> dict: ...

    def set_board_membership(self, platform_id: str, member: bool) -> dict: ...

    def get_game_settings(self) -> dict: ...

    def set_game_settings(self, settings: dict) -> dict: ...

    def get_profile_settings(self) -> dict: ...

    def set_profile_settings(self, settings: dict) -> dict: ...

    def get_personal_profile(self, platform_id: str) -> dict: ...

    def set_personal_profile(self, platform_id: str, profile_text: str) -> dict: ...

    def create_profile_image_upload(self, platform_id: str, upload: dict) -> dict: ...

    def get_profile_image_upload(self, task_id: str) -> dict: ...

    def clear_profile_image(self, platform_id: str) -> dict: ...

    def get_ai_assistant_settings(self) -> dict: ...

    def set_ai_assistant_settings(self, settings: dict) -> dict: ...

    def list_ai_knowledge_cards(self) -> list[dict]: ...

    def create_ai_knowledge_card(self, card: dict) -> dict: ...

    def update_ai_knowledge_card(self, card_id: str, card: dict) -> dict: ...

    def delete_ai_knowledge_card(self, card_id: str) -> dict: ...

    def get_ai_player_memory(self, platform_id: str) -> dict: ...

    def create_ai_player_impression(self, platform_id: str, impression: dict) -> dict: ...

    def update_ai_player_impression(
        self, platform_id: str, entry_id: str, impression: dict
    ) -> dict: ...

    def delete_ai_player_impression(self, platform_id: str, entry_id: str) -> dict: ...

    def clear_ai_player_memory(self, platform_id: str) -> dict: ...

    def get_activity_settings(self) -> dict: ...

    def set_activity_settings(self, settings: dict) -> dict: ...

    def get_number_bomb_settings(self) -> dict: ...

    def set_number_bomb_settings(self, settings: dict) -> dict: ...

    def get_red_packet_settings(self) -> dict: ...

    def set_red_packet_settings(self, settings: dict) -> dict: ...

    def get_current_gameplay(self) -> dict: ...

    def force_end_gameplay(
        self, group_chat_id: str, game_type: str, game_id: str
    ) -> dict: ...

    def get_random_event_settings(self) -> dict: ...

    def set_random_event_settings(self, settings: dict) -> dict: ...

    def list_random_event_submissions(
        self, status: str | None, page: int, page_size: int
    ) -> dict: ...

    def random_event_submission(self, submission_id: str) -> dict: ...

    def update_random_event_submission(
        self, submission_id: str, content: dict, now: str
    ) -> dict: ...

    def approve_random_event_submission(
        self, submission_id: str, reviewer: str, now: str
    ) -> dict: ...

    def reject_random_event_submission(
        self, submission_id: str, reviewer: str, reason: str, now: str
    ) -> dict: ...

    def get_hide_and_seek_settings(self) -> dict: ...

    def set_hide_and_seek_settings(self, settings: dict) -> dict: ...

    def get_memory_assessment_settings(self) -> dict: ...

    def set_memory_assessment_settings(self, settings: dict) -> dict: ...

    def get_undercover_settings(self) -> dict: ...

    def set_undercover_settings(self, settings: dict) -> dict: ...

    def get_undercover_session(self) -> dict: ...

    def get_blame_bomb_settings(self) -> dict: ...

    def set_blame_bomb_settings(self, settings: dict) -> dict: ...

    def list_blame_incidents(self, page: int, page_size: int) -> dict: ...

    def create_blame_incident(self, incident: dict) -> dict: ...

    def update_blame_incident(self, incident_id: str, incident: dict) -> dict: ...

    def delete_blame_incident(self, incident_id: str) -> dict: ...

    def get_blame_bomb_session(self) -> dict: ...

    def end_blame_bomb_session(self) -> dict: ...

    def list_hide_and_seek_scenes(self, page: int, page_size: int) -> dict: ...

    def create_hide_and_seek_scene(self, scene: dict) -> dict: ...

    def update_hide_and_seek_scene(self, scene_id: str, scene: dict) -> dict: ...

    def delete_hide_and_seek_scene(self, scene_id: str) -> dict: ...

    def list_random_event_scenes(self, page: int, page_size: int) -> dict: ...

    def create_random_event_scene(self, scene: dict) -> dict: ...

    def update_random_event_scene(self, scene_id: str, scene: dict) -> dict: ...

    def delete_random_event_scene(self, scene_id: str) -> dict: ...

    def list_today_random_events(self) -> list[dict]: ...

    def list_random_event_submissions(
        self, status: str | None, page: int, page_size: int
    ) -> dict: ...

    def random_event_submission(self, submission_id: str) -> dict: ...

    def update_random_event_submission(
        self, submission_id: str, content: dict, now: str
    ) -> dict: ...

    def approve_random_event_submission(
        self, submission_id: str, reviewer: str, now: str
    ) -> dict: ...

    def reject_random_event_submission(
        self, submission_id: str, reviewer: str, reason: str, now: str
    ) -> dict: ...

    def reschedule_random_event(self, schedule_id: str, scheduled_at: str) -> dict: ...

    def create_today_random_event(self, event: dict) -> dict: ...

    def delete_today_random_event(self, schedule_id: str) -> dict: ...


class CoreClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"X-Core-Token": token},
            timeout=10,
        )

    def status(self) -> dict:
        return self._get("/internal/status")

    def list_group_chats(self, include_deleted: bool = False) -> list[dict]:
        return self._get(
            "/internal/group-chats",
            params={"include_deleted": str(include_deleted).lower()},
        )

    def create_group_chat(self, group: dict) -> dict:
        response = self._client.post("/internal/group-chats", json=group)
        response.raise_for_status()
        return response.json()

    def update_group_chat(self, group_id: str, group: dict) -> dict:
        response = self._client.patch(
            f"/internal/group-chats/{group_id}", json=group
        )
        response.raise_for_status()
        return response.json()

    def delete_group_chat(self, group_id: str, now: str) -> dict:
        response = self._client.request(
            "DELETE", f"/internal/group-chats/{group_id}", json={"now": now}
        )
        response.raise_for_status()
        return response.json()

    def login_state(self) -> str | None:
        heartbeat = self._get("/internal/login-state")
        return None if heartbeat is None else heartbeat["login_state"]

    def get_manual_login_lease(self) -> dict | None:
        return self._get("/internal/admin/login/lease")

    def start_manual_login(self, operator_id: str, operator_name: str) -> dict:
        return self._post_manual_login("start", operator_id, operator_name)

    def finish_manual_login(self, operator_id: str, operator_name: str) -> dict:
        return self._post_manual_login("finish", operator_id, operator_name)

    def cancel_manual_login(self) -> dict:
        response = self._client.post("/internal/admin/login/cancel")
        response.raise_for_status()
        return response.json()

    def enqueue_command(self, command: str) -> dict:
        response = self._client.post(
            "/internal/worker-commands", json={"command": command}
        )
        response.raise_for_status()
        return response.json()

    def list_game_commands(self) -> list[dict]:
        return self._get("/internal/game/commands")

    def set_game_command_enabled(self, command: str, enabled: bool) -> dict:
        response = self._client.patch(
            "/internal/game/commands", json={"command": command, "enabled": enabled}
        )
        response.raise_for_status()
        return response.json()

    def set_game_command_template(
        self, command: str, scenario: str, template: str
    ) -> dict:
        response = self._client.patch(
            "/internal/game/command-templates",
            json={"command": command, "scenario": scenario, "template": template},
        )
        response.raise_for_status()
        return response.json()

    def list_game_users(self, page: int, page_size: int) -> dict:
        return self._get(
            "/internal/game/users", params={"page": page, "page_size": page_size}
        )

    def list_balance_transactions(
        self, platform_id: str, page: int, page_size: int
    ) -> dict:
        return self._get(
            f"/internal/game/users/{platform_id}/balance-transactions",
            params={"page": page, "page_size": page_size},
        )

    def list_employee_group_messages(
        self,
        platform_id: str,
        page: int,
        page_size: int,
        group_chat_id: str | None = None,
    ) -> dict:
        params: dict[str, int | str] = {"page": page, "page_size": page_size}
        if group_chat_id is not None:
            params["group_chat_id"] = group_chat_id
        return self._get(
            f"/internal/game/users/{platform_id}/group-messages",
            params=params,
        )

    def list_game_items(self, page: int, page_size: int) -> dict:
        return self._get(
            "/internal/game/items", params={"page": page, "page_size": page_size}
        )

    def create_game_item(self, item: dict) -> dict:
        response = self._client.post("/internal/game/items", json=item)
        response.raise_for_status()
        return response.json()

    def list_ranks(self) -> list[dict]:
        return self._get("/internal/game/ranks")

    def update_rank(self, rank_id: str, rank: dict) -> dict:
        response = self._client.patch(f"/internal/game/ranks/{rank_id}", json=rank)
        response.raise_for_status()
        return response.json()

    def list_departments(self, page: int, page_size: int) -> dict:
        return self._get(
            "/internal/game/departments", params={"page": page, "page_size": page_size}
        )

    def create_department(self, department: dict) -> dict:
        response = self._client.post("/internal/game/departments", json=department)
        response.raise_for_status()
        return response.json()

    def update_department(self, department_id: str, department: dict) -> dict:
        response = self._client.put(
            f"/internal/game/departments/{department_id}", json=department
        )
        response.raise_for_status()
        return response.json()

    def delete_department(self, department_id: str) -> dict:
        response = self._client.delete(f"/internal/game/departments/{department_id}")
        response.raise_for_status()
        return response.json()

    def list_promotions(self, state: str | None, page: int, page_size: int) -> dict:
        params = {"page": page, "page_size": page_size}
        if state is not None:
            params["state"] = state
        return self._get("/internal/game/promotions", params=params)

    def list_department_requests(
        self, state: str | None, page: int, page_size: int
    ) -> dict:
        params = {"page": page, "page_size": page_size}
        if state is not None:
            params["state"] = state
        return self._get("/internal/game/department-requests", params=params)

    def set_board_membership(self, platform_id: str, member: bool) -> dict:
        response = self._client.post(
            f"/internal/game/users/{platform_id}/board-membership", json={"member": member}
        )
        response.raise_for_status()
        return response.json()

    def get_game_settings(self) -> dict:
        return self._get("/internal/game/settings")

    def set_game_settings(self, settings: dict) -> dict:
        response = self._client.patch("/internal/game/settings", json=settings)
        response.raise_for_status()
        return response.json()

    def get_profile_settings(self) -> dict:
        return self._get("/internal/game/profile-settings")

    def set_profile_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/profile-settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def get_personal_profile(self, platform_id: str) -> dict:
        return self._get(f"/internal/game/users/{platform_id}/profile")

    def set_personal_profile(self, platform_id: str, profile_text: str) -> dict:
        response = self._client.put(
            f"/internal/game/users/{platform_id}/profile",
            json={"profile_text": profile_text},
        )
        response.raise_for_status()
        return response.json()

    def create_profile_image_upload(self, platform_id: str, upload: dict) -> dict:
        response = self._client.post(
            f"/internal/game/users/{platform_id}/profile-image-uploads",
            json=upload,
        )
        response.raise_for_status()
        return response.json()

    def get_profile_image_upload(self, task_id: str) -> dict:
        return self._get(f"/internal/profile-image-uploads/{task_id}")

    def clear_profile_image(self, platform_id: str) -> dict:
        response = self._client.delete(
            f"/internal/game/users/{platform_id}/profile-image"
        )
        response.raise_for_status()
        return response.json()

    def get_number_bomb_settings(self) -> dict:
        return self._get("/internal/game/number-bomb/settings")

    def set_number_bomb_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/number-bomb/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def get_red_packet_settings(self) -> dict:
        return self._get("/internal/game/red-packet/settings")

    def set_red_packet_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/red-packet/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def get_current_gameplay(self) -> dict:
        return self._get("/internal/gameplay/current")

    def force_end_gameplay(
        self, group_chat_id: str, game_type: str, game_id: str
    ) -> dict:
        response = self._client.post(
            f"/internal/gameplay/{group_chat_id}/{game_type}/{game_id}/force-end"
        )
        response.raise_for_status()
        return response.json()

    def get_ai_assistant_settings(self) -> dict:
        return self._get("/internal/game/ai-assistant/settings")

    def set_ai_assistant_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/ai-assistant/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def list_ai_knowledge_cards(self) -> list[dict]:
        return self._get("/internal/game/ai-knowledge-cards")

    def create_ai_knowledge_card(self, card: dict) -> dict:
        response = self._client.post("/internal/game/ai-knowledge-cards", json=card)
        response.raise_for_status()
        return response.json()

    def update_ai_knowledge_card(self, card_id: str, card: dict) -> dict:
        response = self._client.put(
            f"/internal/game/ai-knowledge-cards/{card_id}", json=card
        )
        response.raise_for_status()
        return response.json()

    def delete_ai_knowledge_card(self, card_id: str) -> dict:
        response = self._client.delete(f"/internal/game/ai-knowledge-cards/{card_id}")
        response.raise_for_status()
        return response.json()

    def get_ai_player_memory(self, platform_id: str) -> dict:
        return self._get(f"/internal/game/users/{platform_id}/ai-memory")

    def create_ai_player_impression(self, platform_id: str, impression: dict) -> dict:
        response = self._client.post(
            f"/internal/game/users/{platform_id}/ai-impressions",
            json=impression,
        )
        response.raise_for_status()
        return response.json()

    def update_ai_player_impression(
        self, platform_id: str, entry_id: str, impression: dict
    ) -> dict:
        response = self._client.put(
            f"/internal/game/users/{platform_id}/ai-impressions/{entry_id}",
            json=impression,
        )
        response.raise_for_status()
        return response.json()

    def delete_ai_player_impression(self, platform_id: str, entry_id: str) -> dict:
        response = self._client.delete(
            f"/internal/game/users/{platform_id}/ai-impressions/{entry_id}"
        )
        response.raise_for_status()
        return response.json()

    def clear_ai_player_memory(self, platform_id: str) -> dict:
        response = self._client.delete(f"/internal/game/users/{platform_id}/ai-memory")
        response.raise_for_status()
        return response.json()

    def get_activity_settings(self) -> dict:
        return self._get("/internal/game/activity-settings")

    def set_activity_settings(self, settings: dict) -> dict:
        response = self._client.patch("/internal/game/activity-settings", json=settings)
        response.raise_for_status()
        return response.json()

    def get_random_event_settings(self) -> dict:
        return self._get("/internal/game/random-events/settings")

    def set_random_event_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/random-events/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def get_hide_and_seek_settings(self) -> dict:
        return self._get("/internal/game/hide-and-seek/settings")

    def set_hide_and_seek_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/hide-and-seek/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def get_memory_assessment_settings(self) -> dict:
        return self._get("/internal/game/memory-assessment/settings")

    def set_memory_assessment_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/memory-assessment/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def get_undercover_settings(self) -> dict:
        return self._get("/internal/game/undercover/settings")

    def set_undercover_settings(self, settings: dict) -> dict:
        response = self._client.patch("/internal/game/undercover/settings", json=settings)
        response.raise_for_status()
        return response.json()

    def get_undercover_session(self) -> dict:
        return self._get("/internal/game/undercover/session")

    def get_blame_bomb_settings(self) -> dict:
        return self._get("/internal/game/blame-bomb/settings")

    def set_blame_bomb_settings(self, settings: dict) -> dict:
        response = self._client.patch(
            "/internal/game/blame-bomb/settings", json=settings
        )
        response.raise_for_status()
        return response.json()

    def list_blame_incidents(self, page: int, page_size: int) -> dict:
        return self._get(
            "/internal/game/blame-bomb/incidents",
            params={"page": page, "page_size": page_size},
        )

    def create_blame_incident(self, incident: dict) -> dict:
        response = self._client.post(
            "/internal/game/blame-bomb/incidents", json=incident
        )
        response.raise_for_status()
        return response.json()

    def update_blame_incident(self, incident_id: str, incident: dict) -> dict:
        response = self._client.put(
            f"/internal/game/blame-bomb/incidents/{incident_id}", json=incident
        )
        response.raise_for_status()
        return response.json()

    def delete_blame_incident(self, incident_id: str) -> dict:
        response = self._client.delete(
            f"/internal/game/blame-bomb/incidents/{incident_id}"
        )
        response.raise_for_status()
        return response.json()

    def get_blame_bomb_session(self) -> dict:
        return self._get("/internal/game/blame-bomb/session")

    def end_blame_bomb_session(self) -> dict:
        response = self._client.post("/internal/game/blame-bomb/end")
        response.raise_for_status()
        return response.json()

    def list_hide_and_seek_scenes(self, page: int, page_size: int) -> dict:
        return self._get(
            "/internal/game/hide-and-seek/scenes",
            params={"page": page, "page_size": page_size},
        )

    def create_hide_and_seek_scene(self, scene: dict) -> dict:
        response = self._client.post("/internal/game/hide-and-seek/scenes", json=scene)
        response.raise_for_status()
        return response.json()

    def update_hide_and_seek_scene(self, scene_id: str, scene: dict) -> dict:
        response = self._client.put(
            f"/internal/game/hide-and-seek/scenes/{scene_id}", json=scene
        )
        response.raise_for_status()
        return response.json()

    def delete_hide_and_seek_scene(self, scene_id: str) -> dict:
        response = self._client.delete(f"/internal/game/hide-and-seek/scenes/{scene_id}")
        response.raise_for_status()
        return response.json()

    def list_random_event_scenes(self, page: int, page_size: int) -> dict:
        return self._get(
            "/internal/game/random-events/scenes",
            params={"page": page, "page_size": page_size},
        )

    def create_random_event_scene(self, scene: dict) -> dict:
        response = self._client.post(
            "/internal/game/random-events/scenes", json=scene
        )
        response.raise_for_status()
        return response.json()

    def update_random_event_scene(self, scene_id: str, scene: dict) -> dict:
        response = self._client.put(
            f"/internal/game/random-events/scenes/{scene_id}", json=scene
        )
        response.raise_for_status()
        return response.json()

    def delete_random_event_scene(self, scene_id: str) -> dict:
        response = self._client.delete(
            f"/internal/game/random-events/scenes/{scene_id}"
        )
        response.raise_for_status()
        return response.json()

    def list_today_random_events(self) -> list[dict]:
        return self._get("/internal/game/random-events/today")

    def list_random_event_submissions(
        self, status: str | None, page: int, page_size: int
    ) -> dict:
        params = {"page": page, "page_size": page_size}
        if status is not None:
            params["status"] = status
        return self._get("/internal/random-event-submissions", params=params)

    def random_event_submission(self, submission_id: str) -> dict:
        return self._get(f"/internal/random-event-submissions/{submission_id}")

    def update_random_event_submission(
        self, submission_id: str, content: dict, now: str
    ) -> dict:
        return self._patch(
            f"/internal/random-event-submissions/{submission_id}",
            {"content": content, "now": now},
        )

    def approve_random_event_submission(
        self, submission_id: str, reviewer: str, now: str
    ) -> dict:
        return self._post(
            f"/internal/random-event-submissions/{submission_id}/approve",
            {"reviewer": reviewer, "now": now},
        )

    def reject_random_event_submission(
        self, submission_id: str, reviewer: str, reason: str, now: str
    ) -> dict:
        return self._post(
            f"/internal/random-event-submissions/{submission_id}/reject",
            {"reviewer": reviewer, "reason": reason, "now": now},
        )

    def reschedule_random_event(self, schedule_id: str, scheduled_at: str) -> dict:
        response = self._client.patch(
            f"/internal/game/random-events/today/{schedule_id}",
            json={"scheduled_at": scheduled_at},
        )
        response.raise_for_status()
        return response.json()

    def create_today_random_event(self, event: dict) -> dict:
        response = self._client.post("/internal/game/random-events/today", json=event)
        response.raise_for_status()
        return response.json()

    def delete_today_random_event(self, schedule_id: str) -> dict:
        response = self._client.delete(f"/internal/game/random-events/today/{schedule_id}")
        response.raise_for_status()
        return response.json()

    def trigger_random_event(self, schedule_id: str) -> dict:
        response = self._client.post(
            f"/internal/game/random-events/today/{schedule_id}/trigger"
        )
        response.raise_for_status()
        return response.json()

    def random_event_details(self, schedule_id: str) -> dict:
        return self._get(f"/internal/game/random-events/today/{schedule_id}/details")

    def _get(self, path: str, params: dict | None = None):
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: dict):
        response = self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def _patch(self, path: str, payload: dict):
        response = self._client.patch(path, json=payload)
        response.raise_for_status()
        return response.json()

    def _post_manual_login(
        self, action: str, operator_id: str, operator_name: str
    ) -> dict:
        response = self._client.post(
            f"/internal/admin/login/{action}",
            json={"operator_id": operator_id, "operator_name": operator_name},
        )
        response.raise_for_status()
        return response.json()


class NoVNCClient:
    def __init__(
        self,
        port: int = 16080,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=10
        )

    def get(self, path: str) -> httpx.Response:
        return self._client.get(path)


class NoVNCWebSocketConnector:
    def __init__(
        self,
        port: int = 16080,
        *,
        connect: Callable = websockets.connect,
    ) -> None:
        self._base_url = f"ws://127.0.0.1:{port}"
        self._connect = connect

    def __call__(self, path: str, *, subprotocols: list[str] | None = None):
        return self._connect(
            f"{self._base_url}{path}", subprotocols=subprotocols
        )
