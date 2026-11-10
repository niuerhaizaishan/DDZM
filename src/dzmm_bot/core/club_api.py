"""UID-scoped API for the unified Club and its mahjong table."""

import asyncio
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .club_repository import ClubRateLimitError
from .mahjong_repository import MahjongRateLimitError


class CreateRoomPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    room_type: Literal["casual", "coin"] = "coin"
    stake: Literal[0, 5, 10, 20] = 10
    match_mode: Literal["east", "south"] = "east"


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=0)
    request_id: UUID
    action: Literal[
        "claim", "ready", "unready", "leave", "start",
        "discard", "riichi", "tsumo", "ron", "pass", "chi", "pon", "kan",
        "ankan", "kakan", "kyuushu",
    ]
    payload: dict = Field(default_factory=dict)


class ChatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    text: str = Field(min_length=1, max_length=300)


class SessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=64)
    avatar_url: str | None = Field(default=None, max_length=2048)


class FriendPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_id: UUID


class TaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_key: Literal[
        "employment", "checkin", "random_event", "five_rounds", "activity", "dark_market"
    ]


class CardRoomPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    room_type: Literal["casual", "coin"] = "coin"
    stake: Literal[0, 5, 10, 20] = 10


class CardActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: StrictInt = Field(ge=0)
    request_id: UUID
    action: Literal[
        "claim", "ready", "unready", "leave", "start", "next",
        "check", "call", "raise", "all_in", "fold",
        "look", "compare", "hit", "stand",
    ]
    payload: dict = Field(default_factory=dict)


def _uid(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("ClubUid "):
        raise HTTPException(401, "无法读取玩家身份")
    value = authorization[len("ClubUid "):]
    if not value or len(value) > 255 or any(char.isspace() for char in value):
        raise HTTPException(401, "无法读取玩家身份")
    return value


def _call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (MahjongRateLimitError, ClubRateLimitError) as error:
        raise HTTPException(429, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


async def mahjong_events(repository, room_id, uid, clock, request):
    previous = None
    while not await request.is_disconnected():
        try:
            value = await asyncio.to_thread(repository.mahjong_view, room_id, uid, clock())
        except ValueError:
            yield "event: unavailable\ndata: {}\n\n"
            return
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if encoded != previous:
            yield f"event: snapshot\ndata: {encoded}\n\n"
            previous = encoded
        else:
            yield ": heartbeat\n\n"
        await asyncio.sleep(1)


async def club_social_events(repository, uid, clock, request):
    previous = None
    last_event = asyncio.get_running_loop().time()
    while not await request.is_disconnected():
        value = await asyncio.to_thread(repository.club_social_version, uid, clock())
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        now = asyncio.get_running_loop().time()
        if encoded != previous:
            yield f"event: social\ndata: {encoded}\n\n"
            previous = encoded
            last_event = now
        elif now - last_event >= 15:
            yield ": heartbeat\n\n"
            last_event = now
        await asyncio.sleep(0.5)


async def club_card_events(repository, game, room_id, uid, clock, request):
    previous = None
    last_event = asyncio.get_running_loop().time()
    while not await request.is_disconnected():
        try:
            value = await asyncio.to_thread(
                repository.club_card_view, game, room_id, uid, clock()
            )
        except ValueError:
            yield "event: unavailable\ndata: {}\n\n"
            return
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        now = asyncio.get_running_loop().time()
        if encoded != previous:
            yield f"event: snapshot\ndata: {encoded}\n\n"
            previous = encoded
            last_event = now
        elif now - last_event >= 15:
            yield ": heartbeat\n\n"
            last_event = now
        await asyncio.sleep(0.5)


def club_router(repository, clock):
    router = APIRouter(prefix="/api/club")

    @router.get("/mahjong/rooms")
    def rooms(authorization: str | None = Header(None)):
        return _call(repository.list_mahjong_rooms, _uid(authorization), clock())

    @router.post("/mahjong/rooms")
    def create(body: CreateRoomPayload, authorization: str | None = Header(None)):
        return _call(
            repository.create_mahjong_room,
            _uid(authorization),
            clock(),
            room_type=body.room_type,
            stake=body.stake,
            match_mode=body.match_mode,
            request_id=body.request_id,
        )

    @router.post("/session")
    def session(body: SessionPayload, authorization: str | None = Header(None)):
        return _call(
            repository.ensure_club_player,
            _uid(authorization),
            clock(),
            display_name=body.name,
            avatar_url=body.avatar_url,
        )

    @router.post("/presence")
    def presence(authorization: str | None = Header(None)):
        return _call(repository.club_presence, _uid(authorization), clock())

    @router.get("/room-status/{game}/{room_id}")
    def room_status(
        game: Literal[
            "mahjong", "chess", "doudizhu", "drawguess",
            "texas", "zhajinhua", "blackjack",
        ],
        room_id: UUID,
        authorization: str | None = Header(None),
    ):
        return _call(
            repository.club_room_status,
            game,
            room_id,
            _uid(authorization),
            clock(),
        )

    @router.get("/profile")
    def profile(authorization: str | None = Header(None)):
        return _call(repository.club_profile, _uid(authorization), clock())

    @router.get("/players/{player_id}")
    def player_profile(player_id: UUID, authorization: str | None = Header(None)):
        return _call(repository.club_player_profile, _uid(authorization), player_id, clock())

    @router.get("/channel")
    def channel(authorization: str | None = Header(None)):
        return _call(repository.club_public_messages, _uid(authorization), clock())

    @router.post("/channel")
    def send_channel(body: ChatPayload, authorization: str | None = Header(None)):
        return _call(
            repository.send_club_public_message,
            _uid(authorization),
            body.text,
            clock(),
        )

    @router.get("/social/events")
    async def social_events(request: Request, authorization: str | None = Header(None)):
        uid = _uid(authorization)
        await asyncio.to_thread(_call, repository.club_social_version, uid, clock())
        return StreamingResponse(
            club_social_events(repository, uid, clock, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.get("/friends")
    def friends(authorization: str | None = Header(None)):
        return _call(repository.club_friends, _uid(authorization), clock())

    @router.post("/friends")
    def request_friend(body: FriendPayload, authorization: str | None = Header(None)):
        return _call(
            repository.request_club_friend,
            _uid(authorization),
            body.player_id,
            clock(),
        )

    @router.post("/friends/{request_id}/accept")
    def accept_friend(request_id: UUID, authorization: str | None = Header(None)):
        return _call(
            repository.accept_club_friend,
            _uid(authorization),
            request_id,
            clock(),
        )

    @router.get("/friends/{player_id}/messages")
    def direct_messages(player_id: UUID, authorization: str | None = Header(None)):
        return _call(
            repository.club_direct_messages,
            _uid(authorization),
            player_id,
            clock(),
        )

    @router.post("/friends/{player_id}/messages")
    def send_direct_message(
        player_id: UUID,
        body: ChatPayload,
        authorization: str | None = Header(None),
    ):
        return _call(
            repository.send_club_direct_message,
            _uid(authorization),
            player_id,
            body.text,
            clock(),
        )

    @router.get("/tasks")
    def tasks(authorization: str | None = Header(None)):
        return _call(repository.club_tasks, _uid(authorization), clock())

    @router.post("/tasks/claim")
    def claim_task(body: TaskPayload, authorization: str | None = Header(None)):
        return _call(
            repository.claim_club_task,
            _uid(authorization),
            body.task_key,
            clock(),
        )

    @router.get("/active-room")
    def active_room(authorization: str | None = Header(None)):
        return _call(repository.club_active_room, _uid(authorization), clock())

    @router.get("/cards/{game}/rooms")
    def card_rooms(game: Literal["texas", "zhajinhua", "blackjack"], authorization: str | None = Header(None)):
        return _call(repository.list_club_card_rooms, game, _uid(authorization), clock())

    @router.post("/cards/{game}/rooms")
    def create_card_room(game: Literal["texas", "zhajinhua", "blackjack"], body: CardRoomPayload, authorization: str | None = Header(None)):
        return _call(repository.create_club_card_room, game, _uid(authorization), clock(),
                     room_type=body.room_type, stake=body.stake, request_id=body.request_id)

    @router.get("/cards/{game}/rooms/{room_id}")
    def card_snapshot(game: Literal["texas", "zhajinhua", "blackjack"], room_id: UUID, authorization: str | None = Header(None)):
        return _call(repository.club_card_view, game, room_id, _uid(authorization), clock())

    @router.get("/cards/{game}/rooms/{room_id}/events")
    async def card_events(
        game: Literal["texas", "zhajinhua", "blackjack"],
        room_id: UUID,
        request: Request,
        authorization: str | None = Header(None),
    ):
        uid = _uid(authorization)
        await asyncio.to_thread(_call, repository.club_card_view, game, room_id, uid, clock())
        return StreamingResponse(
            club_card_events(repository, game, room_id, uid, clock, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.post("/cards/{game}/rooms/{room_id}/actions")
    def card_action(game: Literal["texas", "zhajinhua", "blackjack"], room_id: UUID, body: CardActionPayload, authorization: str | None = Header(None)):
        expected = {"raise": {"amount"}, "compare": {"target"}}.get(body.action, set())
        if set(body.payload) != expected:
            raise HTTPException(422, "操作参数不正确")
        return _call(repository.club_card_action, game, room_id, _uid(authorization), body.version,
                     body.request_id, body.action, body.payload, clock())

    @router.post("/cards/{game}/rooms/{room_id}/chat")
    def card_chat(game: Literal["texas", "zhajinhua", "blackjack"], room_id: UUID, body: ChatPayload, authorization: str | None = Header(None)):
        if not body.text.strip():
            raise HTTPException(422, "请输入消息")
        return _call(repository.club_card_chat, game, room_id, _uid(authorization), body.request_id, body.text, clock())

    @router.get("/mahjong/rooms/{room_id}")
    def snapshot(room_id: UUID, authorization: str | None = Header(None)):
        return _call(repository.mahjong_view, room_id, _uid(authorization), clock())

    @router.post("/mahjong/rooms/{room_id}/actions")
    def action(room_id: UUID, body: ActionPayload, authorization: str | None = Header(None)):
        expected = {
            "claim": set(),
            "discard": {"tile"},
            "riichi": {"tile"},
            "chi": {"tiles"},
            "pon": {"tiles"},
            "kan": {"tiles"},
            "ankan": {"tile_type"},
            "kakan": {"meld_index"},
        }.get(body.action, set())
        if set(body.payload) != expected:
            raise HTTPException(422, "操作参数不正确")
        return _call(
            repository.mahjong_action,
            room_id,
            _uid(authorization),
            body.version,
            body.request_id,
            body.action,
            body.payload,
            clock(),
        )

    @router.post("/mahjong/rooms/{room_id}/chat")
    def chat(room_id: UUID, body: ChatPayload, authorization: str | None = Header(None)):
        if not body.text.strip():
            raise HTTPException(422, "请输入消息")
        return _call(
            repository.mahjong_chat,
            room_id,
            _uid(authorization),
            body.request_id,
            body.text,
            clock(),
        )

    @router.get("/mahjong/rooms/{room_id}/events")
    async def events(room_id: UUID, request: Request, authorization: str | None = Header(None)):
        uid = _uid(authorization)
        await asyncio.to_thread(_call, repository.mahjong_view, room_id, uid, clock())
        return StreamingResponse(
            mahjong_events(repository, room_id, uid, clock, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
