"""Authenticated public API for the Gamefy chess board."""

import asyncio
from dataclasses import asdict
from datetime import datetime
import json
import time
from typing import Callable, Literal
from uuid import UUID

import jwt

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .chess_auth import verify_gamefy_token
from .chess_repository import ChessRateLimitError
from .chess_rules import IllegalChessMove
from .repository import CoreRepository


class ClaimPayload(BaseModel):
    code: str | None = Field(default=None, pattern=r"^\d{4}$")


class CreateRoomPayload(BaseModel):
    room_type: Literal["casual", "coin"] = "casual"
    stake: Literal[0, 5, 10, 20] = 0


class MovePayload(BaseModel):
    from_xy: tuple[int, int]
    to_xy: tuple[int, int]
    version: int


class ActionPayload(BaseModel):
    action: str
    version: int


class ChatPayload(BaseModel):
    text: str = Field(min_length=1, max_length=300)


def chess_router(repository: CoreRepository, game_id: str, clock: Callable[[], datetime], *, allow_uid: bool = False) -> APIRouter:
    router = APIRouter(prefix="/api/chess")

    def player_uid(authorization: str | None) -> str:
        if allow_uid and authorization and authorization.startswith("ChessUid "):
            platform_id = authorization[len("ChessUid "):].strip()
        elif authorization and authorization.startswith("Bearer "):
            try:
                platform_id = verify_gamefy_token(authorization[7:], game_id)
            except ValueError as error:
                raise HTTPException(401, str(error)) from error
        else:
            raise HTTPException(401, "请先登录 DZMM")
        return platform_id

    def snapshot(room_id: UUID, platform_id: str) -> dict:
        repository.settle_chess_deadline(room_id, clock())
        try:
            game = repository.get_chess_game(room_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        data = asdict(game)
        data.pop("code", None)
        if platform_id == game.red_platform_id:
            role = "red"
        elif platform_id == game.black_platform_id:
            role = "black"
        elif platform_id == game.creator_platform_id and game.status == "waiting":
            role = "creator"
        else:
            role = "spectator"
        for key in ("creator", "opponent", "red", "black"):
            player = data.get(f"{key}_platform_id")
            data[f"{key}_name"] = repository.club_profile(player, clock())["name"] if player else None
        for key in ("creator", "opponent", "red", "black", "offer"):
            data.pop(f"{key}_platform_id", None)
        return jsonable_encoder({
            "game": data, "role": role, "offer_mine": game.offer_platform_id == platform_id,
            "is_host": game.creator_platform_id == platform_id,
            "messages": repository.chess_messages(room_id),
            "moves": repository.chess_moves(room_id), "server_time": clock(),
        })

    @router.get("/rooms")
    def rooms(authorization: str | None = Header(default=None)) -> list[dict]:
        repository.ensure_club_player(player_uid(authorization), clock())
        return repository.list_chess_rooms(clock())

    @router.post("/rooms")
    def create_room(payload: CreateRoomPayload, authorization: str | None = Header(default=None)) -> dict:
        game = repository.create_chess_game(
            player_uid(authorization), None, None, clock(),
            room_type=payload.room_type, stake=payload.stake,
        )
        return snapshot(game.id, game.creator_platform_id)

    @router.get("/{room_id}")
    def get_game(room_id: UUID, authorization: str | None = Header(default=None)) -> dict:
        return snapshot(room_id, player_uid(authorization))

    @router.post("/{room_id}/claim")
    def claim(room_id: UUID, payload: ClaimPayload, authorization: str | None = Header(default=None)) -> dict:
        pid = player_uid(authorization)
        result = repository.claim_chess_seat(room_id, pid, payload.code, clock())
        if result.status != "claimed":
            raise HTTPException(409, result.status)
        return snapshot(room_id, pid)

    @router.post("/{room_id}/moves")
    def move(room_id: UUID, payload: MovePayload, authorization: str | None = Header(default=None)) -> dict:
        pid = player_uid(authorization)
        try:
            repository.play_chess(room_id, pid, payload.from_xy, payload.to_xy, payload.version, clock())
        except (ValueError, IllegalChessMove) as error:
            raise HTTPException(422, str(error)) from error
        return snapshot(room_id, pid)

    @router.post("/{room_id}/actions")
    def action(room_id: UUID, payload: ActionPayload, authorization: str | None = Header(default=None)) -> dict:
        pid = player_uid(authorization)
        try:
            repository.chess_action(room_id, pid, payload.action, clock(), payload.version)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return snapshot(room_id, pid)

    @router.post("/{room_id}/chat")
    def chat(room_id: UUID, payload: ChatPayload, authorization: str | None = Header(default=None)) -> dict:
        pid = player_uid(authorization)
        try:
            repository.settle_chess_deadline(room_id, clock())
            return repository.chess_chat(room_id, pid, payload.text, clock())
        except ChessRateLimitError as error:
            raise HTTPException(429, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/{room_id}/events")
    async def events(room_id: UUID, request: Request, authorization: str | None = Header(default=None)):
        pid = player_uid(authorization)
        initial = snapshot(room_id, pid)
        expires_at = (time.time() + 1800 if authorization.startswith("ChessUid ")
                      else jwt.decode(authorization[7:], options={"verify_signature": False})["exp"])

        async def stream():
            previous = None
            current = initial
            while time.time() < expires_at and not await request.is_disconnected():
                encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
                if encoded != previous:
                    yield f"event: snapshot\ndata: {encoded}\n\n"
                    previous = encoded
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)
                current = snapshot(room_id, pid)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
