from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect


def _page(items, page, page_size):
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
    }


def assign_super_login_lease(core):
    core.manual_login_lease = {
        "operator_id": "super_admin",
        "operator_name": "超级管理员",
        "expires_at": "2026-08-05T12:03:00+08:00",
    }


@dataclass
class FakeCore:
    login_state_value: str = "ready"
    bot_delivery_state: str = "unknown"
    bot_delivery_error: str | None = None
    commands: list[str] = field(default_factory=list)
    command_definitions: list[dict] = field(
        default_factory=lambda: [
            {
                "command": "/打卡",
                "description": "每日领取 5 摸鱼币",
                "enabled": True,
                "templates": [
                    {
                        "scenario": "checked_in",
                        "label": "打卡成功",
                        "template": "打卡成功，领取 {打卡奖励} 摸鱼币。",
                        "variables": ["{昵称}", "{余额}", "{打卡奖励}", "{日期}"],
                    }
                ],
            }
        ]
    )
    employees: list[dict] = field(default_factory=list)
    balance_ledgers: dict[str, dict] = field(default_factory=dict)
    balance_ledger_requests: list[tuple[str, int, int]] = field(default_factory=list)
    employee_group_messages: dict[str, dict] = field(default_factory=dict)
    employee_group_message_requests: list[tuple[str, int, int, str | None]] = field(
        default_factory=list
    )
    items: list[dict] = field(default_factory=list)
    template_error: bool = False
    game_settings: dict = field(
        default_factory=lambda: {
            "currency_name": "摸鱼币",
            "onboarding_bonus": 0,
            "checkin_reward": 5,
            "weekly_attendance_reward": 5,
            "reset_time_label": "北京时间 00:00",
        }
    )
    profile_settings: dict = field(
        default_factory=lambda: {"edit_cost": 10, "shared_labor": 5, "version": 0}
    )
    personal_profiles: dict[str, str] = field(default_factory=dict)
    personal_profile_images: dict[str, str | None] = field(default_factory=dict)
    profile_uploads: dict[str, dict] = field(default_factory=dict)
    last_profile_upload: dict | None = None
    activity_settings: dict = field(
        default_factory=lambda: {
            "rules": [
                {
                    "level": level,
                    "character_threshold": level * 10,
                    "reward": level,
                }
                for level in range(1, 11)
            ],
            "report_times": ["12:00", "16:00", "20:00", "23:59"],
        }
    )
    number_bomb_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "signup_timeout_minutes": 2,
            "reminder_interval_seconds": 15,
        }
    )
    texas_holdem_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "minimum_players": 2,
            "maximum_players": 9,
            "minimum_buy_in": 20,
            "maximum_buy_in": 200,
            "daily_start_limit": 1,
            "signup_timeout_seconds": 120,
            "action_timeout_seconds": 120,
            "small_blind_percent": 5,
            "big_blind_percent": 10,
        }
    )
    dark_market_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "announcement_group_id": "00000000-0000-0000-0000-000000000001",
            "duration_hours": 3,
            "fee_percent": 5,
            "version": 0,
            "rank_limits": [
                {
                    "rank_id": f"00000000-0000-0000-0000-{level:012d}",
                    "rank_name": f"职位 {level}",
                    "level_label": f"LV{level}",
                    "daily_limit": level if level <= 5 else -1,
                }
                for level in range(1, 12)
            ],
        }
    )
    dark_market_listings: list[dict] = field(
        default_factory=lambda: [
            {
                "id": "00000000-0000-0000-0000-000000000901",
                "public_number": 1,
                "seller_platform_id": "seller-platform",
                "seller_display_name": "后台卖家",
                "buyer_platform_id": None,
                "buyer_display_name": None,
                "current_bidder_platform_id": "buyer-platform",
                "current_bidder_display_name": "后台买家",
                "name": "旧怀表",
                "purpose": "查看时间",
                "details": "停在午夜",
                "gender": "private",
                "starting_price": 10,
                "duration_hours_snapshot": 3,
                "fee_percent_snapshot": 5,
                "state": "active",
                "ends_at": "2026-08-24T18:00:00+08:00",
                "final_amount": None,
                "fee_amount": None,
                "created_at": "2026-08-24T15:00:00+08:00",
                "finished_at": None,
                "disclosure_state": None,
                "disclosure_deadline": None,
                "seller_choice": None,
                "buyer_choice": None,
                "bids": [
                    {
                        "id": "00000000-0000-0000-0000-000000000902",
                        "bidder_platform_id": "buyer-platform",
                        "bidder_display_name": "后台买家",
                        "amount": 20,
                        "state": "current",
                        "created_at": "2026-08-24T15:30:00+08:00",
                        "refunded_at": None,
                        "settled_at": None,
                    }
                ],
            }
        ]
    )
    red_packet_settings: dict = field(
        default_factory=lambda: {
            "expiry_minutes": 10,
            "empty_probability_percent": 5,
        }
    )
    red_packet_settings_requests: list[dict] = field(default_factory=list)
    gameplay_current: dict = field(
        default_factory=lambda: {
            "items": [{
                "group_chat_id": "00000000-0000-0000-0000-000000000001",
                "group_name": "主群聊",
                "game_type": "number_bomb",
                "game_id": "00000000-0000-0000-0000-000000000099",
                "state": "collecting",
                "participants": [
                    {"number": 1, "display_name": "甲", "reported": True},
                    {"number": 2, "display_name": "乙", "reported": False},
                ],
                "signup_deadline": None,
                "next_reminder_at": "2026-08-11T12:00:15+08:00",
                "skip_enabled": True,
            }],
        }
    )
    forced_gameplays: list[tuple[str, str, str]] = field(default_factory=list)
    ai_assistant_settings: dict = field(
        default_factory=lambda: {
            "enabled": False,
            "trigger_prefixes": ["@总监事"],
            "persona": "你是摸鱼公司群的美女总监事。",
            "system_prompt": "保持简短。",
            "over_limit_reply": "今日额度已用完。",
            "failure_reply": "总监事暂时无法回复。",
            "max_response_chars": 600,
            "timeout_seconds": 20,
            "quotas": [
                {
                    "rank_id": f"rank-{level}",
                    "rank_name": f"职位 {level}",
                    "rank_level_label": f"LV{level}",
                    "daily_limit": level,
                }
                for level in range(1, 12)
            ],
        }
    )
    ai_player_memories: dict = field(default_factory=dict)
    ai_knowledge_cards: list[dict] = field(default_factory=list)
    random_event_settings: dict = field(
        default_factory=lambda: {
            "schedule_times": ["00:00", "02:00", "10:00", "14:00", "16:00", "20:00"],
            "signup_notice_template": "可选身份：{可选身份}",
            "signup_timeout_minutes": 15,
            "reminder_interval_minutes": 5,
            "signup_allowed_commands": ["/加入", "/退出"],
            "in_progress_allowed_commands": ["/退出"],
            "blocked_message": "当前有随机事件发生，监事不会处理。",
            "submission_enabled": True,
            "submission_draft_timeout_minutes": 30,
            "submission_max_participants": 99,
            "submission_default_target_rounds": 10,
            "submission_default_event_reward": 6,
            "submission_approval_reward": 10,
            "tipping_duration_seconds": 120,
        }
    )
    random_event_scenes: list[dict] = field(default_factory=list)
    random_event_submissions: list[dict] = field(default_factory=list)
    today_random_events: list[dict] = field(default_factory=list)
    hide_and_seek_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "entry_fee": 1,
            "win_reward": 3,
            "daily_limit": 2,
            "selection_timeout_minutes": 2,
        }
    )
    hide_and_seek_scenes: list[dict] = field(default_factory=list)
    memory_assessment_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "single_daily_limit": 1,
            "single_recall_seconds": 3,
            "duel_recall_seconds": 3,
            "duel_difficulty_level": 5,
            "duel_base_pool": 5,
            "duel_wrong_freeze": 1,
            "duel_wrong_limit": 10,
            "duel_signup_timeout_minutes": 2,
            "duel_answer_timeout_minutes": 10,
            "character_set": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "levels": [
                {"level": level, "answer_length": level * 2 + 3, "reward": level}
                for level in range(1, 6)
            ],
        }
    )
    undercover_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "vote_seconds": 120,
            "whiteboard_win_remaining": 3,
            "signup_timeout_minutes": 2,
            "roles": [
                {"player_count": 4, "civilian_count": 3, "undercover_count": 1, "whiteboard_count": 0},
                {"player_count": 5, "civilian_count": 3, "undercover_count": 1, "whiteboard_count": 1},
                {"player_count": 6, "civilian_count": 4, "undercover_count": 1, "whiteboard_count": 1},
                {"player_count": 7, "civilian_count": 4, "undercover_count": 2, "whiteboard_count": 1},
                {"player_count": 8, "civilian_count": 5, "undercover_count": 2, "whiteboard_count": 1},
            ],
        }
    )
    undercover_session: dict = field(
        default_factory=lambda: {
            "state": None,
            "target_player_count": 0,
            "player_count": 0,
            "queued_count": 0,
            "current_vote_round": 0,
            "vote_deadline": None,
        }
    )
    blame_bomb_settings: dict = field(
        default_factory=lambda: {
            "enabled": True,
            "signup_timeout_seconds": 120,
            "turn_timeout_seconds": 30,
            "durations": [
                {
                    "player_count": player_count,
                    "minimum_seconds": player_count * 10,
                    "maximum_seconds": player_count * 20,
                }
                for player_count in range(2, 11)
            ],
        }
    )
    blame_incidents: list[dict] = field(default_factory=list)
    blame_bomb_session: dict = field(
        default_factory=lambda: {
            "state": None,
            "target_player_count": 0,
            "players": [],
            "incident": None,
            "current_holder": None,
            "temperature": None,
        }
    )
    manual_login_lease: dict | None = None
    ai_assistant_settings_request: dict | None = None
    group_chats: list[dict] = field(default_factory=list)

    def status(self):
        return {
            "state": "healthy",
            "last_heartbeat": "2026-08-04T12:00:00Z",
            "listening": True,
            "listening_desired": True,
            "bot_delivery_state": self.bot_delivery_state,
            "bot_delivery_error": self.bot_delivery_error,
            "queue_counts": {"inbound": 2, "outbound": 1},
            "raw_cookies": "must-not-leak",
            "profile_path": "/secret/profile",
        }

    def list_group_chats(self, include_deleted=False):
        if include_deleted:
            return self.group_chats
        return [item for item in self.group_chats if item.get("deleted_at") is None]

    def create_group_chat(self, group):
        saved = {
            "id": f"00000000-0000-0000-0000-{len(self.group_chats) + 1:012d}",
            **{key: value for key, value in group.items() if key != "now"},
            "chatroom_id": group["chat_url"].split("c=", 1)[1],
            "created_at": group["now"],
            "updated_at": group["now"],
            "deleted_at": None,
            "runtime": None,
        }
        self.group_chats.append(saved)
        return saved

    def update_group_chat(self, group_id, group):
        record = next(item for item in self.group_chats if item["id"] == group_id)
        record.update({key: value for key, value in group.items() if key != "now"})
        record["updated_at"] = group["now"]
        return record

    def delete_group_chat(self, group_id, now):
        record = next(item for item in self.group_chats if item["id"] == group_id)
        record.update(
            {
                "listening_enabled": False,
                "games_enabled": False,
                "random_events_enabled": False,
                "announcements_enabled": False,
                "deleted_at": now,
                "updated_at": now,
            }
        )
        return record

    def login_state(self):
        return self.login_state_value

    def get_manual_login_lease(self):
        return self.manual_login_lease

    def start_manual_login(self, operator_id, operator_name):
        self.manual_login_lease = {
            "operator_id": operator_id,
            "operator_name": operator_name,
            "expires_at": "2026-08-05T12:03:00+08:00",
        }
        self.commands.append("start_auth")
        return self.manual_login_lease

    def finish_manual_login(self, operator_id, operator_name):
        if self.manual_login_lease is None or self.manual_login_lease["operator_id"] != operator_id:
            request = httpx.Request("POST", "http://core/internal/admin/login/finish")
            response = httpx.Response(409, text="manual login is not owned by actor", request=request)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)
        self.manual_login_lease = None
        self.commands.append("finish_auth")
        return {"accepted": True}

    def cancel_manual_login(self):
        cancelled = self.manual_login_lease is not None
        self.manual_login_lease = None
        if cancelled:
            self.commands.append("cancel_auth")
        return {"accepted": cancelled}

    def enqueue_command(self, command):
        self.commands.append(command)
        return {"id": "command-1", "command": command, "status": "pending"}

    def list_game_commands(self):
        return self.command_definitions

    def set_game_command_enabled(self, command, enabled):
        record = next(item for item in self.command_definitions if item["command"] == command)
        record["enabled"] = enabled
        return record

    def set_game_command_template(self, command, scenario, template):
        if self.template_error:
            request = httpx.Request("PATCH", "http://core/internal/game/command-templates")
            response = httpx.Response(422, text="invalid template", request=request)
            raise httpx.HTTPStatusError("invalid template", request=request, response=response)
        record = next(item for item in self.command_definitions if item["command"] == command)
        reply = next(item for item in record["templates"] if item["scenario"] == scenario)
        reply["template"] = template
        return reply

    def list_game_users(self, page, page_size):
        return _page(self.employees, page, page_size)

    def list_balance_transactions(self, platform_id, page, page_size):
        self.balance_ledger_requests.append((platform_id, page, page_size))
        return self.balance_ledgers[platform_id]

    def list_employee_group_messages(
        self, platform_id, page, page_size, group_chat_id=None
    ):
        self.employee_group_message_requests.append(
            (platform_id, page, page_size, group_chat_id)
        )
        return self.employee_group_messages[platform_id]

    def list_game_items(self, page, page_size):
        return _page(self.items, page, page_size)

    def create_game_item(self, item):
        item = {**item, "enabled": True}
        self.items.append(item)
        return item

    def list_ranks(self):
        return getattr(self, "ranks", [])

    def update_rank(self, rank_id, rank):
        index = next(
            index for index, item in enumerate(self.ranks) if item["id"] == rank_id
        )
        saved = {**self.ranks[index], **rank}
        self.ranks[index] = saved
        return saved

    def list_departments(self, page, page_size):
        return _page(getattr(self, "departments", []), page, page_size)

    def create_department(self, department):
        saved = {
            **department,
            "id": f"department-{len(getattr(self, 'departments', [])) + 1}",
            "is_default": False,
            "enabled": True,
        }
        self.departments = [*getattr(self, "departments", []), saved]
        return saved

    def update_department(self, department_id, department):
        index = next(
            index
            for index, item in enumerate(self.departments)
            if item["id"] == department_id
        )
        saved = {**self.departments[index], **department}
        self.departments[index] = saved
        return saved

    def delete_department(self, department_id):
        self.departments = [
            item for item in self.departments if item["id"] != department_id
        ]
        return {"accepted": True}

    def list_promotions(self, state, page, page_size):
        records = getattr(self, "promotions", [])
        if state is not None:
            records = [item for item in records if item["state"] == state]
        return _page(records, page, page_size)

    def list_department_requests(self, state, page, page_size):
        records = getattr(self, "department_requests", [])
        if state is not None:
            records = [item for item in records if item["state"] == state]
        return _page(records, page, page_size)

    def set_board_membership(self, platform_id, member):
        return {"platform_id": platform_id, "member": member}

    def get_game_settings(self):
        return self.game_settings

    def set_game_settings(self, settings):
        self.game_settings = {**settings, "reset_time_label": "北京时间 00:00"}
        return self.game_settings

    def get_profile_settings(self):
        return self.profile_settings

    def set_profile_settings(self, settings):
        if settings["version"] != self.profile_settings["version"]:
            raise httpx.HTTPStatusError(
                "conflict",
                request=httpx.Request("PATCH", "http://core/profile-settings"),
                response=httpx.Response(409, json={"detail": "conflict"}),
            )
        self.profile_settings = {
            "edit_cost": settings["edit_cost"],
            "shared_labor": settings["shared_labor"],
            "version": settings["version"] + 1,
        }
        return self.profile_settings

    def get_personal_profile(self, platform_id):
        if platform_id == "missing":
            raise httpx.HTTPStatusError(
                "not found",
                request=httpx.Request("GET", "http://core/profile"),
                response=httpx.Response(404, json={"detail": "not found"}),
            )
        return {
            "platform_id": platform_id,
            "display_name": "档案员工",
            "profile_text": self.personal_profiles.get(platform_id, ""),
            "profile_image_url": self.personal_profile_images.get(platform_id),
            "profile_version": 0,
            "latest_upload": None,
        }

    def set_personal_profile(self, platform_id, profile_text):
        self.personal_profiles[platform_id] = profile_text
        return self.get_personal_profile(platform_id)

    def create_profile_image_upload(self, platform_id, upload):
        self.last_profile_upload = upload
        task = {
            "id": "upload-1", "platform_id": platform_id, "status": "pending",
            "result_url": None, "failure_summary": None,
            "expected_profile_version": 1,
        }
        self.profile_uploads[task["id"]] = task
        return task

    def get_profile_image_upload(self, task_id):
        return self.profile_uploads[task_id]

    def clear_profile_image(self, platform_id):
        self.personal_profile_images[platform_id] = None
        return self.get_personal_profile(platform_id)

    def get_ai_assistant_settings(self):
        return self.ai_assistant_settings

    def set_ai_assistant_settings(self, settings):
        self.ai_assistant_settings_request = settings
        current = {
            quota["rank_id"]: quota
            for quota in self.ai_assistant_settings["quotas"]
        }
        self.ai_assistant_settings = {
            **settings,
            "quotas": [
                {
                    **current[quota["rank_id"]],
                    "daily_limit": quota["daily_limit"],
                }
                for quota in settings["quotas"]
            ],
        }
        return self.ai_assistant_settings

    def list_ai_knowledge_cards(self):
        return self.ai_knowledge_cards

    def create_ai_knowledge_card(self, card):
        saved = {"id": f"card-{len(self.ai_knowledge_cards) + 1}", **card}
        self.ai_knowledge_cards.append(saved)
        return saved

    def update_ai_knowledge_card(self, card_id, card):
        index = next(
            index for index, item in enumerate(self.ai_knowledge_cards)
            if item["id"] == card_id
        )
        self.ai_knowledge_cards[index] = {"id": card_id, **card}
        return self.ai_knowledge_cards[index]

    def delete_ai_knowledge_card(self, card_id):
        self.ai_knowledge_cards = [
            item for item in self.ai_knowledge_cards if item["id"] != card_id
        ]
        return {"accepted": True}

    def get_ai_player_memory(self, platform_id):
        return self.ai_player_memories.setdefault(
            platform_id,
            {
                "platform_id": platform_id,
                "display_name": "记忆玩家",
                "impressions": [],
                "activity_facts": [],
                "legacy_memory_text": "",
                "updated_at": None,
            },
        )

    def create_ai_player_impression(self, platform_id, impression):
        memory = self.get_ai_player_memory(platform_id)
        saved = {
            "id": f"impression-{len(memory['impressions']) + 1}",
            **impression,
            "source": "admin",
            "pinned": True,
        }
        memory["impressions"].append(saved)
        return saved

    def update_ai_player_impression(self, platform_id, entry_id, impression):
        memory = self.get_ai_player_memory(platform_id)
        index = next(
            index
            for index, entry in enumerate(memory["impressions"])
            if entry["id"] == entry_id
        )
        memory["impressions"][index] = {
            **memory["impressions"][index],
            **impression,
            "source": "admin",
        }
        return memory["impressions"][index]

    def delete_ai_player_impression(self, platform_id, entry_id):
        memory = self.get_ai_player_memory(platform_id)
        memory["impressions"] = [
            entry for entry in memory["impressions"] if entry["id"] != entry_id
        ]
        return {"accepted": True}

    def clear_ai_player_memory(self, platform_id):
        self.get_ai_player_memory(platform_id)["impressions"] = []
        return {"accepted": True}

    def get_activity_settings(self):
        return self.activity_settings

    def set_activity_settings(self, settings):
        self.activity_settings = settings
        return self.activity_settings

    def get_number_bomb_settings(self):
        return self.number_bomb_settings

    def set_number_bomb_settings(self, settings):
        self.number_bomb_settings = settings
        return self.number_bomb_settings

    def get_texas_holdem_settings(self):
        return self.texas_holdem_settings

    def set_texas_holdem_settings(self, settings):
        self.texas_holdem_settings = settings
        return self.texas_holdem_settings

    def get_dark_market_settings(self):
        return self.dark_market_settings

    def set_dark_market_settings(self, settings):
        self.dark_market_settings = {
            **settings,
            "version": settings["expected_version"] + 1,
            "rank_limits": [
                {
                    **item,
                    "rank_name": next(
                        existing["rank_name"]
                        for existing in self.dark_market_settings["rank_limits"]
                        if existing["rank_id"] == item["rank_id"]
                    ),
                    "level_label": next(
                        existing["level_label"]
                        for existing in self.dark_market_settings["rank_limits"]
                        if existing["rank_id"] == item["rank_id"]
                    ),
                }
                for item in settings["rank_limits"]
            ],
        }
        self.dark_market_settings.pop("expected_version", None)
        return self.dark_market_settings

    def list_dark_market_listings(self, status_filter, page, page_size):
        items = self.dark_market_listings
        if status_filter:
            items = [item for item in items if item["state"] == status_filter]
        return _page(items, page, page_size)

    def get_dark_market_listing(self, listing_id):
        return next(item for item in self.dark_market_listings if item["id"] == listing_id)

    def force_delist_dark_market_listing(self, listing_id):
        item = self.get_dark_market_listing(listing_id)
        if item["state"] != "active":
            return {"status": "already_ended"}
        item["state"] = "force_delisted"
        return {"status": "force_delisted"}

    def get_red_packet_settings(self):
        return self.red_packet_settings

    def set_red_packet_settings(self, settings):
        self.red_packet_settings_requests.append(settings)
        self.red_packet_settings = settings
        return self.red_packet_settings

    def get_current_gameplay(self):
        return self.gameplay_current

    def force_end_gameplay(self, group_chat_id, game_type, game_id):
        self.forced_gameplays.append((group_chat_id, game_type, game_id))
        return {"accepted": True}

    def get_random_event_settings(self):
        return self.random_event_settings

    def set_random_event_settings(self, settings):
        self.random_event_settings = settings
        return self.random_event_settings

    def list_random_event_submissions(self, status_filter, page, page_size):
        items = self.random_event_submissions
        if status_filter:
            items = [item for item in items if item["status"] == status_filter]
        return _page(items, page, page_size)

    def random_event_submission(self, submission_id):
        return next(
            item for item in self.random_event_submissions if item["id"] == submission_id
        )

    def update_random_event_submission(self, submission_id, content, now):
        item = self.random_event_submission(submission_id)
        item["content"] = content
        return item

    def approve_random_event_submission(self, submission_id, reviewer, now):
        item = self.random_event_submission(submission_id)
        item["status"] = "approved"
        item["reviewer"] = reviewer
        return item

    def reject_random_event_submission(self, submission_id, reviewer, reason, now):
        item = self.random_event_submission(submission_id)
        item["status"] = "rejected"
        item["reviewer"] = reviewer
        item["rejection_reason"] = reason
        return item

    def list_random_event_scenes(self, page, page_size):
        return _page(self.random_event_scenes, page, page_size)

    def create_random_event_scene(self, scene):
        saved = {**scene, "id": f"scene-{len(self.random_event_scenes) + 1}", "enabled": True}
        self.random_event_scenes.append(saved)
        return saved

    def update_random_event_scene(self, scene_id, scene):
        index = next(
            index
            for index, item in enumerate(self.random_event_scenes)
            if item["id"] == scene_id
        )
        saved = {**scene, "id": scene_id}
        self.random_event_scenes[index] = saved
        return saved

    def delete_random_event_scene(self, scene_id):
        self.random_event_scenes = [
            scene for scene in self.random_event_scenes if scene["id"] != scene_id
        ]
        return {"accepted": True}

    def list_today_random_events(self):
        return self.today_random_events

    def reschedule_random_event(self, schedule_id, scheduled_at):
        schedule = next(item for item in self.today_random_events if item["id"] == schedule_id)
        schedule["scheduled_at"] = scheduled_at
        return schedule

    def create_today_random_event(self, event):
        created = {
            "id": f"schedule-{len(self.today_random_events) + 1}",
            "event_date": "2026-08-04",
            "scheduled_at": event["scheduled_at"],
            "status": "pending",
            "scene_name": "茶水间",
            "event_name": event["event_name"],
            "is_cross_day": False,
        }
        self.today_random_events.append(created)
        return created

    def delete_today_random_event(self, schedule_id):
        before = len(self.today_random_events)
        self.today_random_events = [
            event for event in self.today_random_events if event["id"] != schedule_id
        ]
        return {"accepted": len(self.today_random_events) != before}

    def get_hide_and_seek_settings(self):
        return self.hide_and_seek_settings

    def set_hide_and_seek_settings(self, settings):
        self.hide_and_seek_settings = settings
        return self.hide_and_seek_settings

    def get_memory_assessment_settings(self):
        return self.memory_assessment_settings

    def set_memory_assessment_settings(self, settings):
        self.memory_assessment_settings = settings
        return self.memory_assessment_settings

    def get_undercover_settings(self):
        return self.undercover_settings

    def set_undercover_settings(self, settings):
        self.undercover_settings = settings
        return self.undercover_settings

    def get_undercover_session(self):
        return self.undercover_session

    def get_blame_bomb_settings(self):
        return self.blame_bomb_settings

    def set_blame_bomb_settings(self, settings):
        self.blame_bomb_settings = settings
        return settings

    def list_blame_incidents(self, page, page_size):
        return _page(self.blame_incidents, page, page_size)

    def create_blame_incident(self, incident):
        saved = {
            **incident,
            "id": f"blame-incident-{len(self.blame_incidents) + 1}",
            "enabled": True,
        }
        self.blame_incidents.append(saved)
        return saved

    def update_blame_incident(self, incident_id, incident):
        index = next(
            index
            for index, item in enumerate(self.blame_incidents)
            if item["id"] == incident_id
        )
        saved = {**incident, "id": incident_id}
        self.blame_incidents[index] = saved
        return saved

    def delete_blame_incident(self, incident_id):
        self.blame_incidents = [
            item for item in self.blame_incidents if item["id"] != incident_id
        ]
        return {"accepted": True}

    def get_blame_bomb_session(self):
        return self.blame_bomb_session

    def end_blame_bomb_session(self):
        self.blame_bomb_session = {
            **self.blame_bomb_session,
            "state": None,
            "players": [],
            "incident": None,
            "current_holder": None,
            "temperature": None,
        }
        return {"accepted": True}

    def list_hide_and_seek_scenes(self, page, page_size):
        return _page(self.hide_and_seek_scenes, page, page_size)

    def create_hide_and_seek_scene(self, scene):
        saved = {
            **scene,
            "id": f"hide-scene-{len(self.hide_and_seek_scenes) + 1}",
            "enabled": True,
        }
        self.hide_and_seek_scenes.append(saved)
        return saved

    def update_hide_and_seek_scene(self, scene_id, scene):
        index = next(
            index
            for index, item in enumerate(self.hide_and_seek_scenes)
            if item["id"] == scene_id
        )
        saved = {**scene, "id": scene_id}
        self.hide_and_seek_scenes[index] = saved
        return saved

    def delete_hide_and_seek_scene(self, scene_id):
        before = len(self.hide_and_seek_scenes)
        self.hide_and_seek_scenes = [
            scene for scene in self.hide_and_seek_scenes if scene["id"] != scene_id
        ]
        return {"accepted": len(self.hide_and_seek_scenes) != before}


class FakeConsole:
    def __init__(self):
        self.requests = []

    def get(self, path):
        self.requests.append(path)
        content = {
            "/vnc.html": b'<script src="app/ui.js"></script>',
            "/app/ui.js": b"export const ui = true;",
        }.get(path, b"not found")
        status_code = 200 if path in {"/vnc.html", "/app/ui.js"} else 404
        return httpx.Response(
            status_code,
            content=content,
            headers={
                "content-type": (
                    "text/html; charset=utf-8"
                    if path == "/vnc.html"
                    else "text/javascript"
                )
            },
            request=httpx.Request("GET", f"http://127.0.0.1:16080{path}"),
        )


class FakeUpstreamWebSocket:
    def __init__(self):
        self._frames = iter([b"server-frame"])
        self.sent = []
        self.subprotocol = "binary"

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._frames)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, data):
        self.sent.append(data)


class FakeWebSocketConnection:
    def __init__(self):
        self.paths = []
        self.upstream = FakeUpstreamWebSocket()

    def connect(self, path, *, subprotocols=None):
        self.paths.append((path, subprotocols))
        upstream = self.upstream

        class Connection:
            async def __aenter__(self):
                return upstream

            async def __aexit__(self, *args):
                return None

        return Connection()


@pytest.fixture
def core():
    return FakeCore()


@pytest.fixture
def console():
    return FakeConsole()


@pytest.fixture
def websocket_connection():
    return FakeWebSocketConnection()


@pytest.fixture
def admin_repository():
    from dzmm_bot.admin.repository import AdminRepository
    from dzmm_bot.core.schema import Base

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return AdminRepository(sessionmaker(engine, expire_on_commit=False))


@pytest.fixture
def client(core, console, websocket_connection, admin_repository):
    from dzmm_bot.admin.app import create_app

    return TestClient(
        create_app(
            "admin-secret",
            core,
            repository=admin_repository,
            console_client=console,
            websocket_connector=websocket_connection.connect,
        )
    )


@pytest.fixture
def headers():
    return {
        "X-Admin-Token": "admin-secret",
        "Idempotency-Key": "test-request",
        "If-Match": "0",
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/status"),
        ("post", "/api/worker/start"),
        ("post", "/api/worker/stop"),
        ("post", "/api/worker/restart"),
        ("post", "/api/login/start"),
        ("post", "/api/login/finish"),
        ("post", "/api/session"),
        ("patch", "/api/game/command-templates"),
        ("get", "/api/game/settings"),
        ("get", "/api/game/activity-settings"),
        ("patch", "/api/game/activity-settings"),
        ("get", "/login-console"),
    ],
)
def test_admin_routes_require_admin_token(client, method, path):
    assert client.request(method, path).status_code == 401


def test_health_is_public_and_discloses_no_configuration(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_group_chat_crud_uses_configuration_versioning(client, headers):
    created = client.post(
        "/api/group-chats",
        headers={
            **headers,
            "Idempotency-Key": "group-create",
            "If-Match": "0",
        },
        json={
            "name": "第二群",
            "chat_url": "https://www.aikda.com/chat?c=group-2",
            "listening_enabled": True,
            "games_enabled": True,
            "enabled_game_types": ["number_bomb"],
            "random_events_enabled": False,
            "announcements_enabled": True,
        },
    )

    assert created.status_code == 201
    assert created.json()["version"] == 1
    group_id = created.json()["id"]
    listed = client.get("/api/group-chats", headers=headers)
    assert listed.json()["version"] == 1
    assert listed.json()["items"][0]["name"] == "第二群"
    assert listed.json()["items"][0].get("enabled_game_types") == ["number_bomb"]

    updated = client.patch(
        f"/api/group-chats/{group_id}",
        headers={
            **headers,
            "Idempotency-Key": "group-update",
            "If-Match": "1",
        },
        json={"games_enabled": False, "enabled_game_types": ["texas_holdem"]},
    )
    deleted = client.delete(
        f"/api/group-chats/{group_id}",
        headers={
            **headers,
            "Idempotency-Key": "group-delete",
            "If-Match": "2",
        },
    )

    assert updated.json()["version"] == 2
    assert updated.json()["games_enabled"] is False
    assert updated.json().get("enabled_game_types") == ["texas_holdem"]
    assert deleted.json()["version"] == 3
    assert deleted.json()["deleted_at"] is not None


def test_admin_page_contains_multi_group_controls(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'data-view="group-chats"' in page
    assert 'id="group-chat-list"' in page
    assert 'id="group-chat-name"' in page
    assert 'id="group-chat-url"' in page
    for switch in ("listening", "games", "random-events", "announcements"):
        assert f'id="group-chat-{switch}-enabled"' in page
    for game_type in (
        "red-packet",
        "hide-and-seek",
        "memory-assessment",
        "undercover",
        "blame-bomb",
        "number-bomb",
        "texas-holdem",
    ):
        assert f'id="group-chat-game-{game_type}"' in page
    assert 'requestGame("/api/group-chats"' in script
    assert 'data-employee-group-messages' in script


def test_admin_proxies_categorized_ai_impression_crud(client, headers):
    created = client.post(
        "/api/game/users/player/ai-impressions",
        headers={
            **headers,
            "Idempotency-Key": "impression-create",
            "If-Match": "0",
        },
        json={"category": "expression_style", "content": "偏好先给结论"},
    )

    assert created.status_code == 201
    assert created.json()["pinned"] is True
    entry_id = created.json()["id"]
    updated = client.put(
        f"/api/game/users/player/ai-impressions/{entry_id}",
        headers={
            **headers,
            "Idempotency-Key": "impression-update",
            "If-Match": str(created.json()["version"]),
        },
        json={
            "category": "expression_style",
            "content": "偏好分步骤",
            "pinned": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["pinned"] is False

    deleted = client.delete(
        f"/api/game/users/player/ai-impressions/{entry_id}",
        headers={
            **headers,
            "Idempotency-Key": "impression-delete",
            "If-Match": str(updated.json()["version"]),
        },
    )
    assert deleted.json()["accepted"] is True
    assert client.get(
        "/api/game/users/player/ai-memory", headers=headers
    ).json()["impressions"] == []


def test_admin_proxies_versioned_ai_knowledge_card_crud(client, headers):
    listed = client.get("/api/ai-knowledge-cards", headers=headers)
    payload = {
        "topic": "economy",
        "title": "金币说明",
        "keywords": ["金币"],
        "content": "动态金额以实时数据为准。",
        "enabled": True,
        "priority": 50,
    }
    created = client.post(
        "/api/ai-knowledge-cards",
        headers={**headers, "Idempotency-Key": "card-create", "If-Match": str(listed.json()["version"])},
        json=payload,
    )

    assert created.status_code == 200
    assert created.json()["version"] == 1
    card_id = created.json()["id"]
    updated = client.put(
        f"/api/ai-knowledge-cards/{card_id}",
        headers={**headers, "Idempotency-Key": "card-update", "If-Match": "1"},
        json={**payload, "title": "金币与余额"},
    )
    assert updated.json()["version"] == 2
    removed = client.delete(
        f"/api/ai-knowledge-cards/{card_id}",
        headers={**headers, "Idempotency-Key": "card-delete", "If-Match": "2"},
    )
    assert removed.json() == {"accepted": True, "version": 3}


def test_admin_renders_structured_ai_memory_controls(client, headers):
    page = client.get("/", headers=headers).text
    script = client.get("/static/admin.js", headers=headers).text

    assert 'id="ai-memory-batch-threshold"' in page
    assert 'id="ai-memory-max-entries"' in page
    assert 'id="ai-memory-candidate-expiry-days"' in page
    assert 'id="employee-memory-impressions"' in page
    assert 'id="employee-memory-activity-facts"' in page
    assert "data-impression-category" in script
    assert "memory_text:" not in script


def test_ai_assistant_page_contains_knowledge_card_editor(client, headers):
    page = client.get("/", headers=headers).text
    script = client.get("/static/admin.js", headers=headers).text

    assert 'id="ai-knowledge-card-list"' in page
    assert 'id="ai-knowledge-card-modal"' in page
    assert 'id="ai-knowledge-card-topic"' in page
    assert 'id="ai-knowledge-card-keywords"' in page
    assert '"/api/ai-knowledge-cards"' in script


def test_regular_admin_authenticates_but_cannot_manage_administrators(
    client, admin_repository
):
    admin_repository.create_account("alice", "strong-password")

    login = client.post(
        "/api/auth/login", json={"username": "alice", "password": "strong-password"}
    )

    assert login.status_code == 200
    assert login.json()["account_id"]
    session_headers = {"X-Admin-Session": login.json()["session_token"]}
    assert client.get("/api/status", headers=session_headers).status_code == 200
    assert client.get("/api/admins", headers=session_headers).status_code == 403


def test_super_admin_creates_an_account_once_for_a_retried_request(client, headers):
    request_headers = {**headers, "Idempotency-Key": "create-bob"}

    first = client.post(
        "/api/admins",
        headers=request_headers,
        json={"username": "bob", "password": "strong-password"},
    )
    second = client.post(
        "/api/admins",
        headers=request_headers,
        json={"username": "bob", "password": "strong-password"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert [account["username"] for account in client.get("/api/admins", headers=headers).json()] == ["bob"]


def test_super_admin_retries_account_update_without_repeating_side_effects(
    client, headers, admin_repository
):
    account = admin_repository.create_account("bob", "strong-password")
    request_headers = {**headers, "Idempotency-Key": "disable-bob"}

    first = client.patch(
        f"/api/admins/{account.id}", headers=request_headers, json={"active": False}
    )
    second = client.patch(
        f"/api/admins/{account.id}", headers=request_headers, json={"active": False}
    )

    assert first.status_code == 200
    assert second.json() == first.json()
    assert second.json()["active"] is False


def test_any_admin_can_cancel_manual_login(client, admin_repository, core):
    admin_repository.create_account("alice", "strong-password")
    core.manual_login_lease = {
        "operator_id": "super_admin",
        "operator_name": "超级管理员",
        "expires_at": "2026-08-05T12:03:00+08:00",
    }
    session_token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "strong-password"}
    ).json()["session_token"]

    response = client.post(
        "/api/login/cancel",
        headers={"X-Admin-Session": session_token, "Idempotency-Key": "cancel-login"},
    )

    assert response.status_code == 202
    assert core.commands[-1] == "cancel_auth"


def test_only_login_operator_can_open_console(client, admin_repository, core):
    account = admin_repository.create_account("alice", "strong-password")
    core.manual_login_lease = {
        "operator_id": "super_admin",
        "operator_name": "超级管理员",
        "expires_at": "2026-08-05T12:03:00+08:00",
    }
    session_token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "strong-password"}
    ).json()["session_token"]

    response = client.post("/api/session", headers={"X-Admin-Session": session_token})

    assert response.status_code == 409
    assert account.username == "alice"


def test_admin_dashboard_serves_its_login_and_style_assets(client):
    page = client.get("/")
    stylesheet = client.get("/static/admin.css")

    assert page.status_code == 200
    assert 'id="login-screen"' in page.text
    assert 'id="dashboard"' in page.text
    assert 'data-action="/api/login/start"' in page.text
    assert 'id="login-console-frame"' in page.text
    assert stylesheet.status_code == 200
    assert "--surface" in stylesheet.text


def test_admin_uses_a_grouped_desktop_console_shell(client):
    page = client.get("/").text
    stylesheet = Path("src/dzmm_bot/admin/static/admin.css").read_text()

    assert 'id="page-breadcrumb"' in page
    assert 'id="page-context"' in page
    assert 'class="nav-group"' in page
    assert 'id="employee-pagination"' in page
    assert 'id="random-event-settings-modal"' in page
    assert 'id="notification-region"' in page
    assert 'data-view="undercover"' in page
    assert ".side-nav-shell" in stylesheet
    assert ".sidebar-footer" in stylesheet


def test_admin_script_maps_navigation_views_to_console_page_context():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert "const pageContext" in script
    assert "function setPageContext(view)" in script
    assert "undercover:" in script
    assert "organization:" in script


def test_admin_styles_define_console_data_and_modal_patterns():
    stylesheet = Path("src/dzmm_bot/admin/static/admin.css").read_text()

    assert ".page-context" in stylesheet
    assert ".data-list > .data-row" in stylesheet
    assert ".template-modal-actions" in stylesheet
    assert "position: sticky" in stylesheet


def test_admin_dashboard_exposes_game_navigation_and_proxies_game_data(
    client, headers
):
    page = client.get("/")
    commands = client.get("/api/game/commands", headers=headers)
    disabled = client.patch(
        "/api/game/commands",
        headers=headers,
        json={"command": "/打卡", "enabled": False},
    )
    item = client.post(
        "/api/game/items",
        headers=headers,
        json={"name": "工位午睡券", "description": "眯十分钟。", "price": 5, "stock": 3},
    )

    assert 'id="nav-commands"' in page.text
    assert 'id="nav-employees"' in page.text
    assert 'id="nav-shop"' in page.text
    assert commands.json()[0]["command"] == "/打卡"
    assert disabled.json()["enabled"] is False
    assert item.status_code == 201


def test_admin_proxies_paginated_employee_and_item_pages(client, headers, core):
    core.employees = [
        {
            "platform_id": f"user-{index}",
            "display_name": f"员工{index}",
            "employee_number": index + 1,
            "balance": 5,
            "joined_at": "2026-08-05T09:00:00+08:00",
        }
        for index in range(21)
    ]
    core.items = [
        {
            "name": f"午休券{index}",
            "description": "可安心休息十分钟。",
            "price": 5,
            "stock": 1,
            "enabled": True,
        }
        for index in range(21)
    ]

    employees = client.get("/api/game/users?page=2&page_size=20", headers=headers)
    items = client.get("/api/game/items?page=2&page_size=20", headers=headers)

    assert employees.json()["page"] == 2
    assert employees.json()["items"][0]["display_name"] == "员工20"
    assert employees.json()["items"][0]["employee_number"] == 21
    assert items.json()["page_size"] == 20
    assert items.json()["items"][0]["name"] == "午休券20"


def test_admin_proxies_employee_balance_ledger(client, headers, core):
    core.balance_ledgers["user-1"] = {
        "platform_id": "user-1",
        "display_name": "员工1",
        "current_balance": 12,
        "items": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "amount": -3,
                "source": "shop",
                "source_label": "商店购买",
                "occurred_at": "2026-08-14T09:00:00+08:00",
                "balance_after": 12,
            }
        ],
        "page": 2,
        "page_size": 20,
        "total": 21,
        "pages": 2,
    }

    response = client.get(
        "/api/game/users/user-1/balance-transactions?page=2&page_size=20",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["source_label"] == "商店购买"
    assert core.balance_ledger_requests == [("user-1", 2, 20)]
    assert client.get(
        "/api/game/users/user-1/balance-transactions"
    ).status_code == 401
    assert client.get(
        "/api/game/users/user-1/balance-transactions?page=0", headers=headers
    ).status_code == 422


def test_admin_proxies_employee_group_message_filter(client, headers, core):
    group_id = "00000000-0000-0000-0000-000000000002"
    core.employee_group_messages["user-1"] = {
        "platform_id": "user-1",
        "display_name": "员工1",
        "items": [],
        "page": 2,
        "page_size": 20,
        "total": 0,
        "pages": 0,
    }

    response = client.get(
        "/api/game/users/user-1/group-messages",
        params={"page": 2, "page_size": 20, "group_chat_id": group_id},
        headers=headers,
    )

    assert response.status_code == 200
    assert core.employee_group_message_requests == [
        ("user-1", 2, 20, group_id)
    ]


def test_admin_proxies_rank_department_and_promotion_pages_with_board_boundary(
    client, headers, core, admin_repository
):
    core.ranks = [{"id": "rank-1", "name": "实习生", "level_label": "LV1"}]
    core.departments = [
        {
            "id": "department-1",
            "name": "未分配部门",
            "description": "",
            "is_default": True,
            "enabled": True,
        }
    ]
    core.promotions = [{"number": 1, "applicant_name": "小明", "state": "pending"}]
    core.department_requests = [{"number": 1, "applicant_name": "小明", "state": "pending"}]
    admin_repository.create_account("alice", "strong-password")
    session_token = client.post(
        "/api/auth/login", json={"username": "alice", "password": "strong-password"}
    ).json()["session_token"]

    ranks = client.get("/api/game/ranks", headers=headers)
    departments = client.get(
        "/api/game/departments?page=1&page_size=20", headers=headers
    )
    promotions = client.get(
        "/api/game/promotions?state=pending&page=1&page_size=20", headers=headers
    )
    department_requests = client.get(
        "/api/game/department-requests?state=pending&page=1&page_size=20",
        headers=headers,
    )
    forbidden = client.post(
        "/api/game/users/user-1/board-membership",
        headers={"X-Admin-Session": session_token},
        json={"member": True},
    )
    granted = client.post(
        "/api/game/users/user-1/board-membership",
        headers={**headers, "Idempotency-Key": "grant-board"},
        json={"member": True},
    )

    assert ranks.json()[0]["name"] == "实习生"
    assert departments.json()["items"][0]["name"] == "未分配部门"
    assert promotions.json()["items"][0]["number"] == 1
    assert department_requests.json()["items"][0]["number"] == 1
    assert forbidden.status_code == 403
    assert granted.status_code == 200
    assert granted.json()["board_member"] is True


def test_admin_dashboard_exposes_pagination_and_mutation_controls(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'id="employee-pagination"' in page
    assert 'id="shop-pagination"' in page
    assert 'id="settings-weekly-attendance-reward"' in page
    assert 'id="nav-organization"' in page
    assert 'id="rank-modal"' in page
    assert 'id="department-modal"' in page
    assert 'id="department-request-list"' in page
    assert "runMutation" in script
    assert "renderPagination" in script
    assert "formatEmployeeNumber" in script
    assert "employee.employee_number" in script
    assert "/api/game/users?page=${page}&page_size=${pageSizeFor(\"employees\")}" in script
    assert "/api/game/items?page=${page}&page_size=${pageSizeFor(\"shop\")}" in script
    assert '"保存中…"' in script
    assert '"上架中…"' in script
    assert "请填写场景名称、报名公告和每个事件的名称、开场白" in script
    assert "weekly_attendance_reward" in script
    assert "/api/game/ranks" in script
    assert "/api/game/departments" in script
    assert "/api/game/promotions" in script
    assert "/api/game/department-requests" in script


def test_admin_accepts_the_browser_item_form_json_body(client, headers):
    response = client.post(
        "/api/game/items",
        headers={**headers, "Content-Type": "text/plain;charset=UTF-8"},
        content=(
            '{"name":"午休券","description":"可安心休息十分钟。",'
            '"price":5,"stock":1}'
        ),
    )

    assert response.status_code == 201
    assert response.json()["name"] == "午休券"


def test_admin_proxies_game_settings(client, headers, core):
    initial = client.get("/api/game/settings", headers=headers)
    updated = client.patch(
        "/api/game/settings",
        headers=headers,
        json={
            "currency_name": "工分",
            "onboarding_bonus": 3,
            "checkin_reward": 7,
            "weekly_attendance_reward": 9,
        },
    )

    assert initial.json()["currency_name"] == "摸鱼币"
    assert updated.json()["currency_name"] == "工分"
    assert updated.json()["version"] == 1
    assert core.game_settings["checkin_reward"] == 7
    assert core.game_settings["weekly_attendance_reward"] == 9


def test_admin_proxies_profile_settings_and_employee_profile(client, headers, core):
    initial = client.get("/api/game/profile-settings", headers=headers)
    updated = client.patch(
        "/api/game/profile-settings",
        headers={**headers, "Idempotency-Key": "profile-settings-1"},
        json={"edit_cost": 12, "shared_labor": 8, "version": 0},
    )
    shown = client.get("/api/game/users/profile-user/profile", headers=headers)
    saved = client.put(
        "/api/game/users/profile-user/profile",
        headers=headers,
        json={"profile_text": "管理员填写"},
    )
    cleared = client.put(
        "/api/game/users/profile-user/profile",
        headers=headers,
        json={"profile_text": ""},
    )

    assert initial.json() == {"edit_cost": 10, "shared_labor": 5, "version": 0}
    assert updated.json() == {"edit_cost": 12, "shared_labor": 8, "version": 1}
    assert shown.json()["profile_text"] == ""
    assert saved.json()["profile_text"] == "管理员填写"
    assert cleared.json()["profile_text"] == ""
    assert core.personal_profiles["profile-user"] == ""


def test_admin_rejects_invalid_personal_profile_payloads(client, headers):
    assert client.patch(
        "/api/game/profile-settings",
        headers=headers,
        json={"edit_cost": -1, "shared_labor": 5, "version": 0},
    ).status_code == 422
    assert client.put(
        "/api/game/users/profile-user/profile",
        headers=headers,
        json={"profile_text": "字" * 801},
    ).status_code == 422


def test_admin_exposes_personal_profile_controls(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'id="profile-settings-card"' in page
    assert 'id="edit-profile-settings"' in page
    assert 'id="profile-settings-edit-cost"' in page
    assert 'id="profile-settings-shared-labor"' in page
    assert 'id="employee-profile-text"' in page
    assert 'id="employee-profile-image"' in page
    assert 'id="employee-profile-image-file"' in page
    assert 'id="upload-employee-profile-image"' in page
    assert 'id="clear-employee-profile-image"' in page
    assert 'maxlength="800"' in page
    assert 'data-personal-profile=' in script
    assert '"/api/game/profile-settings"' in script
    assert '`/api/game/users/${platformId}/profile`' in script
    assert 'Idempotency-Key' in script


def test_admin_exposes_employee_balance_ledger_modal(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'id="employee-balance-ledger-modal"' in page
    assert 'id="employee-balance-ledger-summary"' in page
    assert 'id="employee-balance-ledger-list"' in page
    assert 'id="employee-balance-ledger-pagination"' in page
    assert "历史流水从 2026-08-05 起记录" in page
    assert 'data-balance-ledger=' in script
    assert '`/api/game/users/${platformId}/balance-transactions?page=${page}&page_size=20`' in script
    assert "formatSignedAmount" in script
    assert "当前余额" in script
    assert "暂无摸鱼币流水记录" in script
    assert "上一页" in script
    assert "下一页" in script
    assert "读取摸鱼币流水失败" in script
    assert "employeeBalanceLedgerRequestId" in script
    assert 'renderPagination(document.querySelector("#employee-balance-ledger-pagination")' in script


def test_admin_uploads_and_clears_employee_profile_image(
    tmp_path, core, console, websocket_connection, admin_repository, headers
):
    from dzmm_bot.admin.app import create_app

    upload_dir = tmp_path / "profile-uploads"
    client = TestClient(create_app(
        "admin-secret", core, repository=admin_repository,
        console_client=console, websocket_connector=websocket_connection.connect,
        profile_upload_dir=upload_dir,
    ))
    core.personal_profiles["profile-user"] = "个人介绍"

    uploaded = client.post(
        "/api/game/users/profile-user/profile-image",
        headers=headers,
        files={"file": ("profile.png", b"\x89PNG\r\n\x1a\nimage-data", "image/png")},
    )
    task_id = uploaded.json()["id"]
    status_response = client.get(
        f"/api/game/profile-image-uploads/{task_id}", headers=headers
    )
    cleared = client.delete(
        "/api/game/users/profile-user/profile-image", headers=headers
    )

    assert uploaded.status_code == 202
    assert status_response.json()["status"] == "pending"
    assert cleared.status_code == 200
    saved_path = Path(core.last_profile_upload["temp_path"])
    assert saved_path.parent == upload_dir
    assert saved_path.read_bytes() == b"\x89PNG\r\n\x1a\nimage-data"
    assert upload_dir.stat().st_mode & 0o777 == 0o700
    assert saved_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("filename", "content_size", "mime_type"),
    [
        ("profile.gif", 3, "image/gif"),
        ("profile.png", 12, "image/png"),
        ("profile.png", 10 * 1024 * 1024 + 1, "image/png"),
    ],
)
def test_admin_rejects_invalid_profile_image_upload(
    tmp_path, core, console, websocket_connection, admin_repository, headers,
    filename, content_size, mime_type,
):
    from dzmm_bot.admin.app import create_app

    client = TestClient(create_app(
        "admin-secret", core, repository=admin_repository,
        console_client=console, websocket_connector=websocket_connection.connect,
        profile_upload_dir=tmp_path,
    ))

    response = client.post(
        "/api/game/users/profile-user/profile-image",
        headers=headers,
        files={"file": (filename, b"x" * content_size, mime_type)},
    )

    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_admin_rejects_stale_configuration_write(client, headers):
    first = client.patch(
        "/api/game/settings",
        headers=headers,
        json={
            "currency_name": "工分",
            "onboarding_bonus": 3,
            "checkin_reward": 7,
            "weekly_attendance_reward": 9,
        },
    )
    second = client.patch(
        "/api/game/settings",
        headers={**headers, "Idempotency-Key": "stale-settings"},
        json={
            "currency_name": "银元",
            "onboarding_bonus": 3,
            "checkin_reward": 7,
            "weekly_attendance_reward": 9,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["version"] == 1


def test_admin_proxies_activity_settings(client, headers, core):
    initial = client.get("/api/game/activity-settings", headers=headers)
    updated = client.patch(
        "/api/game/activity-settings",
        headers=headers,
        json={
            "rules": core.activity_settings["rules"],
            "report_times": ["09:30", "18:00"],
        },
    )

    assert initial.json()["report_times"] == ["12:00", "16:00", "20:00", "23:59"]
    assert updated.json()["report_times"] == ["09:30", "18:00"]


def test_admin_proxies_hide_and_seek_scene_creation_with_version_and_idempotency(
    client, headers, core
):
    initial = client.get("/api/game/hide-and-seek/settings", headers=headers)
    response = client.post(
        "/api/game/hide-and-seek/scenes",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "hide-scene-1",
        },
        json={"name": "打印区"},
    )

    assert response.status_code == 201
    assert core.hide_and_seek_scenes[0]["name"] == "打印区"
    assert "version" in response.json()


def test_admin_proxies_memory_assessment_settings_with_versioning(client, headers, core):
    initial = client.get("/api/game/memory-assessment/settings", headers=headers)
    response = client.patch(
        "/api/game/memory-assessment/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "memory-assessment-settings-1",
        },
        json={
            **core.memory_assessment_settings,
            "single_recall_seconds": 4,
            "duel_base_pool": 6,
        },
    )

    assert initial.status_code == 200
    assert response.status_code == 200
    assert response.json()["single_recall_seconds"] == 4
    assert response.json()["duel_base_pool"] == 6
    assert response.json()["version"] == 1


def test_admin_proxies_undercover_settings_and_public_session(client, headers, core):
    initial = client.get("/api/game/undercover/settings", headers=headers)
    response = client.patch(
        "/api/game/undercover/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "undercover-settings-1",
        },
        json={
            **core.undercover_settings,
            "vote_seconds": 90,
        },
    )
    session = client.get("/api/game/undercover/session", headers=headers)

    assert initial.status_code == 200
    assert response.status_code == 200
    assert response.json()["vote_seconds"] == 90
    assert response.json()["version"] == 1
    assert session.status_code == 200
    assert session.json()["state"] is None
    assert "roles" not in session.json()


def test_admin_proxies_blame_bomb_configuration_cards_and_session(
    client, headers, core
):
    initial = client.get("/api/game/blame-bomb/settings", headers=headers)
    updated = client.patch(
        "/api/game/blame-bomb/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "blame-settings-1",
        },
        json={**core.blame_bomb_settings, "turn_timeout_seconds": 20},
    )
    created = client.post(
        "/api/game/blame-bomb/incidents",
        headers={
            **headers,
            "If-Match": str(updated.json()["version"]),
            "Idempotency-Key": "blame-incident-1",
        },
        json={
            "name": "咖啡事故",
            "description": "咖啡泼到了报表",
            "keywords": ["咖啡", "报表"],
        },
    )
    incident_id = created.json()["id"]
    changed = client.put(
        f"/api/game/blame-bomb/incidents/{incident_id}",
        headers={
            **headers,
            "If-Match": str(created.json()["version"]),
            "Idempotency-Key": "blame-incident-2",
        },
        json={
            "name": "会议事故",
            "description": "会议材料发错了",
            "keywords": ["会议", "材料"],
            "enabled": False,
        },
    )
    cards = client.get("/api/game/blame-bomb/incidents", headers=headers)
    session = client.get("/api/game/blame-bomb/session", headers=headers)
    ended = client.post("/api/game/blame-bomb/end", headers=headers)
    deleted = client.delete(
        f"/api/game/blame-bomb/incidents/{incident_id}",
        headers={
            **headers,
            "If-Match": str(changed.json()["version"]),
            "Idempotency-Key": "blame-incident-3",
        },
    )

    assert initial.status_code == 200
    assert updated.json()["turn_timeout_seconds"] == 20
    assert created.status_code == 201
    assert changed.json()["enabled"] is False
    assert cards.json()["items"][0]["name"] == "会议事故"
    assert session.json()["state"] is None
    assert ended.json() == {"accepted": True}
    assert deleted.json()["accepted"] is True


def test_admin_exposes_blame_bomb_management_surface(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'data-view="blame-bomb"' in page
    assert 'id="blame-bomb-settings-card"' in page
    assert 'id="blame-bomb-session-card"' in page
    assert 'id="blame-incident-list"' in page
    assert 'id="edit-blame-bomb-settings"' in page
    assert 'id="create-blame-incident"' in page
    assert '"/api/game/blame-bomb/settings"' in script
    assert '"/api/game/blame-bomb/session"' in script
    assert '["/甩锅游戏", "/甩锅游戏"]' in script
    assert "explosion_deadline" not in script
    assert "turn_deadline" not in script


def test_admin_page_exposes_activity_settings_modal(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'id="edit-activity-settings"' in page
    assert 'id="activity-settings-modal"' in page
    assert "openActivitySettingsModal" in script
    assert "/api/game/activity-settings" in script


def test_admin_relay_updates_a_command_template(client, headers, core):
    response = client.patch(
        "/api/game/command-templates",
        headers=headers,
        json={
            "command": "/打卡",
            "scenario": "checked_in",
            "template": "{昵称} +{打卡奖励}",
        },
    )

    assert response.status_code == 200
    assert response.json()["template"] == "{昵称} +{打卡奖励}"
    assert core.command_definitions[0]["templates"][0]["template"] == "{昵称} +{打卡奖励}"


def test_admin_relay_rejects_a_template_without_required_fields(client, headers):
    response = client.patch(
        "/api/game/command-templates", headers=headers, json={"command": "/余额"}
    )

    assert response.status_code == 422


def test_admin_relay_forwards_core_template_validation_failure(client, headers, core):
    core.template_error = True

    response = client.patch(
        "/api/game/command-templates",
        headers=headers,
        json={
            "command": "/打卡",
            "scenario": "checked_in",
            "template": "{商店列表}",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid template"}


def test_command_library_keeps_template_scenarios_inside_a_modal(client):
    """Fails if scenario cards return to the command-library main page."""
    page = client.get("/")
    script = client.get("/static/admin.js")

    assert 'id="template-modal"' in page.text
    assert 'id="template-modal-scenario"' in page.text
    assert 'id="template-modal-input"' in page.text
    assert "data-command-templates" in script.text
    assert "data-variable" in script.text
    assert "closeTemplateModal" in script.text
    assert "/api/game/command-templates" in script.text


def test_admin_page_exposes_game_settings_navigation_and_modal(client):
    page = client.get("/").text
    script = client.get("/static/admin.js").text

    assert 'data-view="settings"' in page
    assert 'id="settings-view"' in page
    assert 'id="settings-modal"' in page
    assert "/api/game/settings" in script


def test_gameplay_settings_is_not_hidden_with_the_overview_view(client):
    """Fails if the gameplay settings view is nested inside the overview view."""

    class ViewParentParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.parents = {}

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if attributes.get("id") == "settings-view":
                self.parents["settings-view"] = self.stack[-1] if self.stack else None
            self.stack.append((tag, attributes))

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    del self.stack[index:]
                    return

    parser = ViewParentParser()
    parser.feed(client.get("/").text)

    assert parser.parents["settings-view"] == (
        "div",
        {"class": "dashboard-views"},
    )


def test_status_returns_only_safe_operational_fields(client, headers):
    response = client.get("/api/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "state": "healthy",
        "last_heartbeat": "2026-08-04T12:00:00Z",
        "listening": True,
        "listening_desired": True,
        "bot_delivery_state": "unknown",
        "bot_delivery_error": None,
        "queue_counts": {"inbound": 2, "outbound": 1},
    }
    assert "cookie" not in response.text.lower()
    assert "profile" not in response.text.lower()


def test_concrete_core_client_uses_aggregate_status_endpoint():
    from dzmm_bot.admin.core_client import CoreClient

    def handle(request):
        assert request.headers["X-Core-Token"] == "core-secret"
        assert request.url.path == "/internal/status"
        return httpx.Response(
            200,
            json={
                "state": "auth_required",
                "last_heartbeat": "2026-08-04T12:00:00Z",
                "queue_counts": {
                    "inbound_accepted": 3,
                    "outbound_pending": 2,
                    "worker_commands_pending": 1,
                },
            },
        )

    transport = httpx.MockTransport(handle)
    http_client = httpx.Client(
        base_url="http://127.0.0.1:18120",
        headers={"X-Core-Token": "core-secret"},
        transport=transport,
    )

    assert CoreClient("unused", "unused", client=http_client).status() == {
        "state": "auth_required",
        "last_heartbeat": "2026-08-04T12:00:00Z",
        "queue_counts": {
            "inbound_accepted": 3,
            "outbound_pending": 2,
            "worker_commands_pending": 1,
        },
    }


def test_concrete_core_client_requests_employee_balance_ledger_page():
    from dzmm_bot.admin.core_client import CoreClient

    def handle(request):
        assert request.headers["X-Core-Token"] == "core-secret"
        assert request.url.path == "/internal/game/users/user-1/balance-transactions"
        assert dict(request.url.params) == {"page": "2", "page_size": "20"}
        return httpx.Response(200, json={"items": [], "total": 0})

    transport = httpx.MockTransport(handle)
    http_client = httpx.Client(
        base_url="http://127.0.0.1:18120",
        headers={"X-Core-Token": "core-secret"},
        transport=transport,
    )

    result = CoreClient("unused", "unused", client=http_client).list_balance_transactions(
        "user-1", 2, 20
    )

    assert result == {"items": [], "total": 0}


def test_concrete_core_client_gets_and_sets_texas_holdem_settings():
    from dzmm_bot.admin.core_client import CoreClient

    settings = {
        "enabled": True,
        "minimum_players": 2,
        "maximum_players": 9,
        "minimum_buy_in": 20,
        "maximum_buy_in": 200,
        "daily_start_limit": 1,
        "signup_timeout_seconds": 120,
        "action_timeout_seconds": 120,
        "small_blind_percent": 5,
        "big_blind_percent": 10,
    }
    methods = []

    def handle(request):
        assert request.headers["X-Core-Token"] == "core-secret"
        assert request.url.path == "/internal/game/texas-holdem/settings"
        methods.append(request.method)
        if request.method == "PATCH":
            assert json.loads(request.content) == settings
        return httpx.Response(200, json=settings)

    http_client = httpx.Client(
        base_url="http://127.0.0.1:18120",
        headers={"X-Core-Token": "core-secret"},
        transport=httpx.MockTransport(handle),
    )
    core = CoreClient("unused", "unused", client=http_client)

    assert core.get_texas_holdem_settings() == settings
    assert core.set_texas_holdem_settings(settings) == settings
    assert methods == ["GET", "PATCH"]


def test_concrete_core_client_uses_dark_market_contract_paths():
    from dzmm_bot.admin.core_client import CoreClient

    calls = []

    def handle(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/force-delist"):
            return httpx.Response(200, json={"status": "force_delisted"})
        if request.url.path.endswith("/settings"):
            return httpx.Response(200, json={"enabled": True, "version": 0})
        if request.url.path.endswith("/listings"):
            return httpx.Response(200, json={"items": [], "total": 0})
        return httpx.Response(200, json={"id": "listing-1"})

    http_client = httpx.Client(
        base_url="http://127.0.0.1:18120",
        headers={"X-Core-Token": "core-secret"},
        transport=httpx.MockTransport(handle),
    )
    core = CoreClient("unused", "unused", client=http_client)
    core.get_dark_market_settings()
    core.set_dark_market_settings({"enabled": True, "expected_version": 0})
    core.list_dark_market_listings("active", 2, 10)
    core.get_dark_market_listing("listing-1")
    core.force_delist_dark_market_listing("listing-1")

    assert calls == [
        ("GET", "/internal/game/dark-market/settings", {}),
        ("PATCH", "/internal/game/dark-market/settings", {}),
        (
            "GET",
            "/internal/game/dark-market/listings",
            {"page": "2", "page_size": "10", "status": "active"},
        ),
        ("GET", "/internal/game/dark-market/listings/listing-1", {}),
        (
            "POST",
            "/internal/game/dark-market/listings/listing-1/force-delist",
            {},
        ),
    ]


def test_novnc_websocket_connector_targets_only_loopback():
    from dzmm_bot.admin.core_client import NoVNCWebSocketConnector

    calls = []
    expected_connection = object()

    def connect(uri, *, subprotocols=None):
        calls.append((uri, subprotocols))
        return expected_connection

    connector = NoVNCWebSocketConnector(port=16080, connect=connect)

    assert connector("/websockify", subprotocols=["binary"]) is expected_connection
    assert calls == [
        ("ws://127.0.0.1:16080/websockify", ["binary"]),
    ]


@pytest.mark.parametrize(
    ("action", "command"),
    [
        ("start", "resume_listening"),
        ("stop", "pause_listening"),
        ("restart", "restart_browser"),
    ],
)
def test_worker_actions_create_durable_core_commands(
    client, headers, core, action, command
):
    response = client.post(f"/api/worker/{action}", headers=headers)

    assert response.status_code == 202
    assert response.json() == {
        "id": "command-1",
        "command": command,
        "status": "pending",
    }
    assert core.commands == [command]


def test_login_start_creates_only_durable_command_when_auth_required(
    client, headers, core
):
    core.login_state_value = "auth_required"

    response = client.post("/api/login/start", headers=headers)

    assert response.status_code == 202
    assert core.commands == ["start_auth"]


def test_login_start_allows_shared_verification_when_bot_requires_captcha(
    client, headers, core
):
    core.login_state_value = "ready"
    core.bot_delivery_state = "captcha_required"
    core.bot_delivery_error = "captcha_required"

    response = client.post("/api/login/start", headers=headers)

    assert response.status_code == 202
    assert core.commands == ["start_auth"]


def test_admin_page_shows_bot_delivery_status(client):
    page = client.get("/")

    assert 'id="bot-delivery-state"' in page.text
    assert 'id="bot-delivery-help"' in page.text


def test_login_start_rejects_other_states(client, headers, core):
    core.login_state_value = "ready"

    response = client.post("/api/login/start", headers=headers)

    assert response.status_code == 409
    assert core.commands == []


def test_login_finish_creates_only_durable_command_during_auth(
    client, headers, core
):
    core.login_state_value = "auth_in_progress"
    core.manual_login_lease = {
        "operator_id": "super_admin",
        "operator_name": "超级管理员",
        "expires_at": "2026-08-05T12:03:00+08:00",
    }

    response = client.post("/api/login/finish", headers=headers)

    assert response.status_code == 202
    assert core.commands == ["finish_auth"]


def test_login_console_is_proxied_only_during_auth(
    client, headers, core, console
):
    blocked = client.get("/login-console", headers=headers)
    core.login_state_value = "auth_in_progress"
    assign_super_login_lease(core)
    client.post("/api/session", headers=headers)
    allowed = client.get("/login-console")

    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert 'src="app/ui.js"' in allowed.text
    assert console.requests == ["/vnc.html"]


def test_console_rejects_token_without_current_console_session(client, headers, core):
    core.login_state_value = "auth_in_progress"
    assign_super_login_lease(core)

    response = client.get("/login-console", headers=headers)

    assert response.status_code == 401


def test_admin_token_creates_httponly_console_session_without_url_secret(
    client, headers, core
):
    core.manual_login_lease = {
        "operator_id": "super_admin",
        "operator_name": "超级管理员",
        "expires_at": "2026-08-05T12:03:00+08:00",
    }
    response = client.post("/api/session", headers=headers)

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "dzmm_admin_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/login-console" in cookie
    assert "admin-secret" not in cookie
    assert "admin-secret" not in response.headers.get("location", "")


def test_console_session_authenticates_root_and_relative_assets(
    client, headers, core, console
):
    core.manual_login_lease = {
        "operator_id": "super_admin",
        "operator_name": "超级管理员",
        "expires_at": "2026-08-05T12:03:00+08:00",
    }
    client.post("/api/session", headers=headers)
    core.login_state_value = "auth_in_progress"

    root = client.get("/login-console")
    asset = client.get("/login-console/app/ui.js")

    assert root.status_code == 200
    assert root.url.path == "/login-console/"
    assert root.url.params["path"] == "login-console/websockify"
    assert asset.status_code == 200
    assert asset.text == "export const ui = true;"
    assert console.requests == ["/vnc.html", "/app/ui.js"]


def test_console_root_forces_authenticated_novnc_websocket_path(
    client, headers, core
):
    assign_super_login_lease(core)
    client.post("/api/session", headers=headers)
    core.login_state_value = "auth_in_progress"

    response = client.get("/login-console/?path=websockify")

    assert response.status_code == 200
    assert response.url.params["path"] == "login-console/websockify"


def test_console_root_redirects_duplicate_attacker_first_path(
    client, headers, core, console
):
    assign_super_login_lease(core)
    client.post("/api/session", headers=headers)
    core.login_state_value = "auth_in_progress"

    response = client.get(
        "/login-console/?path=attacker&path=login-console%2Fwebsockify",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == (
        "/login-console/?path=login-console%2Fwebsockify"
    )
    assert console.requests == []


def test_console_assets_reject_session_when_auth_is_not_active(
    client, headers, core
):
    assign_super_login_lease(core)
    client.post("/api/session", headers=headers)
    core.login_state_value = "ready"

    assert client.get("/login-console/app/ui.js").status_code == 409


def test_console_asset_proxy_preserves_upstream_not_found(client, headers, core):
    assign_super_login_lease(core)
    client.post("/api/session", headers=headers)
    core.login_state_value = "auth_in_progress"

    response = client.get("/login-console/missing.js")

    assert response.status_code == 404
    assert response.text == "not found"


def test_console_websocket_requires_session_and_active_auth(
    client, headers, core, websocket_connection
):
    core.login_state_value = "auth_in_progress"
    with pytest.raises(WebSocketDisconnect) as missing_session:
        with client.websocket_connect("/login-console/websockify"):
            pass
    assert missing_session.value.code == 4401

    assign_super_login_lease(core)
    client.post("/api/session", headers=headers)
    core.login_state_value = "ready"
    with pytest.raises(WebSocketDisconnect) as wrong_state:
        with client.websocket_connect("/login-console/websockify"):
            pass
    assert wrong_state.value.code == 4409

    core.login_state_value = "auth_in_progress"
    with client.websocket_connect(
        "/login-console/websockify", subprotocols=["binary"]
    ) as websocket:
        assert websocket.accepted_subprotocol == "binary"
        assert websocket.receive_bytes() == b"server-frame"

    assert websocket_connection.paths == [("/websockify", ["binary"])]


def test_index_contains_status_fields_and_only_declared_actions(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "last-heartbeat" in response.text
    assert "queue-counts" in response.text
    assert "listener-state" in response.text
    assert "listener-help" in response.text
    assert "群聊平台适配器尚未配置" not in response.text

    class ListenerControlParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.controls = {}

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            control_id = attributes.get("id")
            if control_id in {"start-listening", "pause-listening"}:
                self.controls[control_id] = attributes

    parser = ListenerControlParser()
    parser.feed(response.text)
    assert parser.controls == {
        "start-listening": {
            "id": "start-listening",
            "data-action": "/api/worker/start",
            "type": "button",
        },
        "pause-listening": {
            "id": "pause-listening",
            "data-action": "/api/worker/stop",
            "type": "button",
        },
    }
    for path in (
        "/api/worker/start",
        "/api/worker/stop",
        "/api/worker/restart",
        "/api/login/start",
        "/api/login/finish",
    ):
        assert path in response.text


def test_admin_configures_random_event_settings_and_creates_scene(client, headers, core):
    settings = client.patch(
        "/api/game/random-events/settings",
        headers=headers,
        json={
            "schedule_times": ["10:00", "14:00"],
            "signup_notice_template": "可选身份：{可选身份}",
            "signup_timeout_minutes": 15,
            "reminder_interval_minutes": 5,
            "signup_allowed_commands": ["/加入", "/退出"],
            "in_progress_allowed_commands": ["/退出"],
            "blocked_message": "当前有随机事件发生，监事不会处理。",
            "submission_enabled": True,
            "submission_draft_timeout_minutes": 45,
            "submission_max_participants": 88,
            "submission_default_target_rounds": 12,
            "submission_default_event_reward": 7,
            "submission_approval_reward": 11,
            "tipping_duration_seconds": 180,
        },
    )
    scene = client.post(
        "/api/game/random-events/scenes",
        headers={**headers, "Idempotency-Key": "scene-create", "If-Match": "1"},
        json={
            "name": "茶水间",
            "signup_text": "今天的公司茶水间随机事件来啦，快点加入吧。",
            "openings": ["咖啡机突然发出一声巨响。"],
            "reward": 4,
            "target_rounds": 10,
            "seats": [{"role": "员工", "capacity": 2}],
        },
    )

    assert settings.status_code == 200
    assert settings.json()["version"] == 1
    assert core.random_event_settings["submission_draft_timeout_minutes"] == 45
    assert core.random_event_settings["tipping_duration_seconds"] == 180
    assert scene.status_code == 201
    assert scene.json()["name"] == "茶水间"
    assert scene.json()["openings"] == ["咖啡机突然发出一声巨响。"]
    assert client.get("/api/game/random-events/scenes", headers=headers).json()["items"]


def test_admin_random_event_submission_review_is_visible_and_actionable(
    client, headers, core
):
    core.random_event_submissions.append(
        {
            "id": "submission-1",
            "number": "RE-0001",
            "status": "pending",
            "content": {
                "scene_name": "夜班文件失踪案",
                "signup_text": "夜班文件不见了，快来报名。",
                "participant_count": 2,
                "roles": [
                    {"name": "调查员", "capacity": 1},
                    {"name": "目击者", "capacity": 1},
                ],
                "events": [
                    {"name": "档案室", "opening_text": "{调查员}开始寻找文件。"}
                ],
            },
            "target_rounds": 10,
            "event_reward": 6,
            "approval_reward": 10,
            "submitter": {"display_name": "投稿人", "employee_number": 15},
            "submitted_at": "2026-08-15T10:00:00+08:00",
            "reviewer": None,
            "rejection_reason": None,
        }
    )

    listed = client.get(
        "/api/game/random-events/submissions?status=pending", headers=headers
    )
    approved = client.post(
        "/api/game/random-events/submissions/submission-1/approve",
        headers={**headers, "Idempotency-Key": "approve-submission-1"},
    )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["number"] == "RE-0001"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_random_event_submission_admin_controls_are_rendered(client):
    page = client.get("/").text

    assert 'data-management-tab="submissions"' in page
    assert 'id="random-event-submission-list"' in page
    assert 'id="random-event-submission-modal"' in page
    assert 'id="random-event-submission-enabled"' in page


def test_random_event_scene_validation_identifies_missing_fields(client, headers):
    response = client.post(
        "/api/game/random-events/scenes",
        headers=headers,
        json={"name": "茶水间"},
    )

    assert response.status_code == 422
    assert "signup_text" in response.json()["detail"]


def test_admin_can_add_and_remove_today_random_event(client, headers):
    created = client.post(
        "/api/game/random-events/today",
        headers={**headers, "Idempotency-Key": "event-create", "If-Match": "0"},
        json={
            "scene_id": "scene-1",
            "event_name": "咖啡事故",
            "scheduled_at": "2026-08-04T21:00:00+08:00",
        },
    )

    assert created.status_code == 200
    assert created.json()["status"] == "pending"
    deleted = client.delete(
        f"/api/game/random-events/today/{created.json()['id']}",
        headers={
            **headers,
            "Idempotency-Key": "event-delete",
            "If-Match": str(created.json()["version"]),
        },
    )
    assert deleted.json()["accepted"] is True


def test_random_event_scene_modal_uses_split_copy_fields(client):
    page = client.get("/").text

    assert 'id="random-event-scene-signup"' in page
    assert 'id="random-event-scene-openings"' in page


def test_random_event_settings_modal_exposes_command_permissions(client):
    page = client.get("/").text
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'id="random-event-blocked-message"' in page
    assert 'id="random-event-tipping-duration"' in page
    assert 'id="random-event-signup-command-permissions"' in page
    assert 'id="random-event-progress-command-permissions"' in page
    assert "tipping_duration_seconds" in script
    assert 'tipping: "打赏中"' in script
    assert "tipping_deadline" in script
    assert "tip_total" in script


def test_admin_exposes_hide_and_seek_configuration_surface(client):
    page = client.get("/").text
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'data-view="hide-and-seek"' in page
    assert 'id="hide-and-seek-view"' in page
    assert 'id="hide-and-seek-settings-modal"' in page
    assert "loadHideAndSeek" in script
    assert '"/api/game/hide-and-seek/settings"' in script


def test_admin_exposes_memory_assessment_configuration_surface(client):
    page = client.get("/").text
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'data-view="memory-assessment"' in page
    assert 'id="memory-assessment-settings-modal"' in page
    assert "loadMemoryAssessment" in script
    assert '"/api/game/memory-assessment/settings"' in script


def test_admin_exposes_undercover_configuration_surface(client):
    page = client.get("/").text
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'data-view="undercover"' in page
    assert 'id="undercover-view"' in page
    assert 'id="undercover-settings-modal"' in page
    assert "loadUndercover" in script
    assert '"/api/game/undercover/settings"' in script
    assert '"/api/game/undercover/session"' in script


def test_admin_serves_and_saves_ai_assistant_settings(client, headers, core):
    response = client.get("/api/ai-assistant/settings", headers=headers)

    assert response.status_code == 200
    assert response.json()["trigger_prefixes"] == ["@总监事"]
    assert "key" not in response.text.lower()

    saved = client.patch(
        "/api/ai-assistant/settings",
        headers={
            **headers,
            "Idempotency-Key": "ai-settings-save-1",
            "If-Match": str(response.json()["version"]),
        },
        json={
            **{key: value for key, value in response.json().items() if key != "version"},
            "enabled": True,
            "trigger_prefixes": ["@总监事", "/总监事", "/饭饭"],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["enabled"] is True
    assert core.ai_assistant_settings["enabled"] is True
    assert core.ai_assistant_settings["trigger_prefixes"] == [
        "@总监事", "/总监事", "/饭饭"
    ]
    assert all(
        set(quota) == {"rank_id", "daily_limit"}
        for quota in core.ai_assistant_settings_request["quotas"]
    )


def test_admin_exposes_ai_assistant_configuration_surface(client):
    page = client.get("/").text
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'data-view="ai-assistant"' in page
    assert 'id="ai-assistant-settings-modal"' in page
    assert "每日调用上限" in page
    assert 'id="ai-assistant-trigger-prefixes"' in page
    assert 'id="ai-assistant-max-chars" type="number" min="1" max="10000"' in page
    assert '"/api/ai-assistant/settings"' in script


def test_admin_static_assets_disable_browser_cache(client):
    response = client.get("/static/admin.js")

    assert response.headers["cache-control"] == "no-store"


def test_admin_serves_random_event_submission_url_helper_without_cache(client):
    response = client.get("/static/admin_urls.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"


def test_admin_index_disables_browser_cache(client):
    response = client.get("/")

    assert response.headers["cache-control"] == "no-store"


def test_admin_uses_standard_toast_notifications(client):
    page = client.get("/").text
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'id="notification-region"' in page
    assert "showNotification" in script


def test_status_refresh_does_not_show_a_success_notification():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()
    refresh = script.split("async function refresh()", 1)[1].split(
        "async function submitAction", 1
    )[0]

    assert 'setResult("状态已更新", "success")' not in refresh


def test_random_event_details_modal_keeps_header_visible_and_scrolls_entries(client):
    page = client.get("/").text
    stylesheet = Path("src/dzmm_bot/admin/static/admin.css").read_text()

    assert 'class="template-modal-card event-details-modal-card"' in page
    assert ".event-details-modal-card" in stylesheet
    assert "#random-event-details-list" in stylesheet
    assert "overflow-y: auto" in stylesheet


def test_random_event_rules_modal_uses_internal_scroll_for_long_settings(client):
    page = client.get("/").text
    stylesheet = Path("src/dzmm_bot/admin/static/admin.css").read_text()

    assert 'class="template-modal-card random-event-settings-modal-card"' in page
    assert ".random-event-settings-modal-card" in stylesheet
    assert "max-height: calc(100vh - 40px)" in stylesheet
    assert "overflow-y: auto" in stylesheet


def test_random_event_scene_script_submits_openings_list():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert "signup_text: signupText" in script
    assert "openings" in script


def test_random_event_scene_script_renders_role_variable_buttons():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert "renderRandomEventSceneOpeningVariables" in script
    assert "data-random-event-role-variable" in script


def test_random_event_script_offers_template_and_today_actions():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert "data-random-event-name" in script
    assert "data-trigger-random-event" in script
    assert "openRandomEventDetailsModal" in script


def test_admin_account_list_bypasses_browser_cache():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'requestGame("/api/admins", {cache: "no-store"})' in script


def test_admin_styles_define_unified_management_components():
    stylesheet = Path("src/dzmm_bot/admin/static/admin.css").read_text()

    for selector in (
        ".management-tabs",
        ".management-tab",
        ".management-pane",
        ".list-toolbar",
        ".list-scroll",
        ".page-size-select",
        ".data-table",
        ".status-badge",
    ):
        assert selector in stylesheet
    assert "max-height" in stylesheet
    assert "overflow-y: auto" in stylesheet


def test_admin_groups_management_content_into_tabs_and_bounded_lists(client):
    page = client.get("/").text

    assert 'data-management-tabs="events"' in page
    assert 'data-management-tab="today"' in page
    assert 'data-management-pane="scenes"' in page
    assert 'class="list-scroll"' in page
    assert 'class="list-toolbar"' in page


def test_admin_script_supports_tabs_and_configurable_page_sizes():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert "function initializeManagementTabs()" in script
    assert "function renderPageSizeControl(" in script
    assert "const pageSizeOptions = [5, 10, 15, 20, 50]" in script
    assert "function renderLocalPagination(" in script


def test_admin_script_supports_management_filters_and_status_badges():
    script = Path("src/dzmm_bot/admin/static/admin.js").read_text()

    assert "function initializeListFilters()" in script
    assert "function statusBadge(" in script
    assert 'data-list-filter="commands"' in Path("src/dzmm_bot/admin/templates/index.html").read_text()
    assert 'data-list-filter="employees"' in Path("src/dzmm_bot/admin/templates/index.html").read_text()
    assert 'data-list-filter="random-event-scenes"' in Path("src/dzmm_bot/admin/templates/index.html").read_text()
    assert 'data-list-page-size="shop"' in Path("src/dzmm_bot/admin/templates/index.html").read_text()
    assert 'data-list-page-size="ranks"' in Path("src/dzmm_bot/admin/templates/index.html").read_text()


def test_admin_updates_random_event_scene_with_named_events(client, headers):
    created = client.post(
        "/api/game/random-events/scenes",
        headers=headers,
        json={
            "name": "茶水间",
            "signup_text": "报名",
            "events": [{"name": "咖啡事故", "opening_text": "开场"}],
            "reward": 1,
            "target_rounds": 1,
            "seats": [{"role": "员工", "capacity": 1}],
        },
    )
    scene = created.json()

    updated = client.put(
        f"/api/game/random-events/scenes/{scene['id']}",
        headers={
            **headers,
            "Idempotency-Key": "test-request-update",
            "If-Match": str(scene["version"]),
        },
        json={**scene, "events": [{"name": "新事件", "opening_text": "新开场"}]},
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["events"][0]["name"] == "新事件"


def test_admin_proxies_versioned_number_bomb_settings(client, headers, core):
    initial = client.get("/api/game/number-bomb/settings", headers=headers)
    updated = client.patch(
        "/api/game/number-bomb/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "number-bomb-timeout-1",
        },
        json={
            "enabled": False,
            "signup_timeout_minutes": 3,
            "reminder_interval_seconds": 20,
        },
    )

    assert initial.json()["signup_timeout_minutes"] == 2
    assert updated.json()["enabled"] is False
    assert updated.json()["reminder_interval_seconds"] == 20
    assert updated.json()["version"] == initial.json()["version"] + 1
    assert core.number_bomb_settings == {
        "enabled": False,
        "signup_timeout_minutes": 3,
        "reminder_interval_seconds": 20,
    }


def test_admin_proxies_versioned_texas_holdem_settings(client, headers, core):
    initial = client.get("/api/game/texas-holdem/settings", headers=headers)
    payload = {
        **core.texas_holdem_settings,
        "enabled": False,
        "signup_timeout_seconds": 180,
        "action_timeout_seconds": 90,
    }
    updated = client.patch(
        "/api/game/texas-holdem/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "texas-holdem-settings-1",
        },
        json=payload,
    )

    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["action_timeout_seconds"] == 90
    assert core.texas_holdem_settings == payload


def test_admin_rejects_invalid_texas_holdem_settings_before_relay(client, headers, core):
    initial = client.get("/api/game/texas-holdem/settings", headers=headers)
    original = dict(core.texas_holdem_settings)
    invalid = {**original, "minimum_players": 8, "maximum_players": 3}

    response = client.patch(
        "/api/game/texas-holdem/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "texas-holdem-settings-invalid",
        },
        json=invalid,
    )

    assert response.status_code == 422
    assert core.texas_holdem_settings == original


def test_admin_proxies_dark_market_settings_history_and_force_delist(
    client, headers, core
):
    initial = client.get("/api/game/dark-market/settings", headers=headers)
    assert initial.status_code == 200
    payload = {
        "enabled": True,
        "announcement_group_id": "00000000-0000-0000-0000-000000000001",
        "duration_hours": 4,
        "fee_percent": 8,
        "rank_limits": [
            {"rank_id": item["rank_id"], "daily_limit": 2}
            for item in initial.json()["rank_limits"]
        ],
    }
    updated = client.patch(
        "/api/game/dark-market/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "dark-market-settings-1",
        },
        json=payload,
    )
    assert updated.status_code == 200
    assert updated.json()["fee_percent"] == 8
    assert core.dark_market_settings["duration_hours"] == 4

    listed = client.get(
        "/api/game/dark-market/listings?status=active&page=1&page_size=20",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["seller_display_name"] == "后台卖家"
    listing_id = listed.json()["items"][0]["id"]
    detail = client.get(
        f"/api/game/dark-market/listings/{listing_id}", headers=headers
    )
    assert detail.json()["bids"][0]["bidder_display_name"] == "后台买家"

    removed = client.post(
        f"/api/game/dark-market/listings/{listing_id}/force-delist",
        headers={
            **headers,
            "If-Match": str(updated.json()["version"]),
            "Idempotency-Key": "dark-market-delist-1",
        },
    )
    replay = client.post(
        f"/api/game/dark-market/listings/{listing_id}/force-delist",
        headers={
            **headers,
            "If-Match": str(updated.json()["version"]),
            "Idempotency-Key": "dark-market-delist-1",
        },
    )
    assert removed.json()["status"] == "force_delisted"
    assert replay.json() == removed.json()


def test_admin_rejects_invalid_dark_market_settings_before_relay(
    client, headers, core
):
    initial = client.get("/api/game/dark-market/settings", headers=headers)
    original = dict(core.dark_market_settings)
    response = client.patch(
        "/api/game/dark-market/settings",
        headers={
            **headers,
            "If-Match": str(initial.json()["version"]),
            "Idempotency-Key": "dark-market-invalid",
        },
        json={
            "enabled": True,
            "announcement_group_id": None,
            "duration_hours": 25,
            "fee_percent": 0,
            "rank_limits": [],
        },
    )
    assert response.status_code == 422
    assert core.dark_market_settings == original


def test_admin_proxies_versioned_red_packet_settings_idempotently(
    client, headers, core
):
    assert client.get("/api/game/red-packet/settings").status_code == 401
    initial = client.get("/api/game/red-packet/settings", headers=headers)
    write_headers = {
        **headers,
        "If-Match": str(initial.json()["version"]),
        "Idempotency-Key": "red-packet-settings-1",
    }
    payload = {"expiry_minutes": 20, "empty_probability_percent": 8}
    updated = client.patch(
        "/api/game/red-packet/settings", headers=write_headers, json=payload
    )
    replayed = client.patch(
        "/api/game/red-packet/settings", headers=write_headers, json=payload
    )

    assert initial.json() == {
        "expiry_minutes": 10,
        "empty_probability_percent": 5,
        "version": 0,
    }
    assert updated.json() == {
        "expiry_minutes": 20,
        "empty_probability_percent": 8,
        "version": 1,
    }
    assert replayed.json() == updated.json()
    assert core.red_packet_settings_requests == [payload]


@pytest.mark.parametrize(
    "payload",
    (
        {"expiry_minutes": 0, "empty_probability_percent": 5},
        {"expiry_minutes": 61, "empty_probability_percent": 5},
        {"expiry_minutes": 10, "empty_probability_percent": -1},
        {"expiry_minutes": 10, "empty_probability_percent": 31},
        {"expiry_minutes": 10},
        {
            "expiry_minutes": 10,
            "empty_probability_percent": 5,
            "unknown": True,
        },
    ),
)
def test_admin_rejects_invalid_red_packet_settings(client, headers, payload):
    assert client.patch(
        "/api/game/red-packet/settings", headers=headers, json=payload
    ).status_code == 422


def test_red_packet_settings_surface_has_controls_and_api_contract():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert "随机运气红包" in page
    assert 'id="red-packet-settings-card"' in page
    assert 'id="edit-red-packet-settings"' in page
    assert 'id="red-packet-expiry-minutes"' in page
    assert 'id="red-packet-empty-probability"' in page
    assert 'id="save-red-packet-settings"' in page
    assert '"/api/game/red-packet/settings"' in script
    assert "expiry_minutes < 1 || expiry_minutes > 60" in script
    assert (
        "empty_probability_percent < 0 || empty_probability_percent > 30"
        in script
    )


def test_number_bomb_settings_surface_has_new_controls_and_gameplay_card():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'id="number-bomb-settings-card"' in page
    assert 'id="edit-number-bomb-settings"' in page
    assert 'id="gameplay-current-card"' in page
    assert 'id="force-end-current-game"' in page
    assert 'id="number-bomb-enabled"' in page
    assert 'id="number-bomb-signup-minutes"' in page
    assert 'id="number-bomb-reminder-seconds"' in page
    assert 'id="number-bomb-timeout-minutes"' not in page
    assert 'id="memory-assessment-signup-timeout"' in page
    assert 'id="undercover-signup-timeout"' in page
    assert "/api/game/number-bomb/settings" in script
    assert "/api/gameplay/current" in script


def test_texas_holdem_admin_surface_has_settings_and_public_table_state():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'data-view="texas-holdem"' in page
    assert 'id="texas-holdem-settings-card"' in page
    assert 'id="texas-holdem-session-card"' in page
    assert 'id="edit-texas-holdem-settings"' in page
    assert 'id="texas-holdem-enabled"' in page
    assert 'id="save-texas-holdem-settings"' in page
    assert "底牌不会出现在管理端" in page
    assert "/api/game/texas-holdem/settings" in script
    assert '.filter((item) => item.game_type === "texas_holdem")' in script
    assert "games.map((game) =>" in script
    assert "hole_cards" not in script


def test_number_bomb_admin_surface_shows_tournament_progress_points_and_retirement():
    root = Path(__file__).resolve().parents[2]
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'item.mode === "points_tournament"' in script
    assert "participant.total_points" in script
    assert 'participant.state === "retired"' in script
    assert "item.maximum_rounds" in script


def test_admin_relays_current_gameplay_and_versioned_force_end(client, headers, core):
    current = client.get("/api/gameplay/current", headers=headers)
    ended = client.post(
        "/api/gameplay/00000000-0000-0000-0000-000000000001/number_bomb/00000000-0000-0000-0000-000000000099/force-end",
        headers={
            **headers,
            "If-Match": str(current.json()["version"]),
            "Idempotency-Key": "force-game-1",
        },
    )

    assert current.status_code == 200
    assert current.json()["items"][0]["participants"][1]["reported"] is False
    assert ended.json()["accepted"] is True
    assert ended.json()["version"] == current.json()["version"] + 1
    assert core.forced_gameplays == [
        (
            "00000000-0000-0000-0000-000000000001",
            "number_bomb",
            "00000000-0000-0000-0000-000000000099",
        )
    ]
