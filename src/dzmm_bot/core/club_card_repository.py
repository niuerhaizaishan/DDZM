"""Persistence and coin settlement for Club card-table modules."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from random import SystemRandom
from uuid import UUID, uuid4

from sqlalchemy import select

from .club_card_games import GAMES, PLAYER_LIMITS, apply_action, new_hand, public_view
from .schema import (
    ClubCardMessageRecord as Message,
    ClubCardHandRecord as Hand,
    ClubCardRequestRecord as Receipt,
    ClubCardRoomRecord as Room,
    ClubPlayerRecord,
    UserRecord,
)


STAKES = {5, 10, 20}
TURN_TIMEOUT_SECONDS = 30


class ClubCardRepositoryMixin:
    _club_card_random = SystemRandom()

    @staticmethod
    def _club_card_room(session, room_id: UUID, *, lock: bool = True) -> Room:
        query = select(Room).where(Room.id == room_id)
        if lock:
            query = query.with_for_update()
        room = session.scalar(query)
        if room is None:
            raise ValueError("房间不存在")
        return room

    @staticmethod
    def _club_card_account(session, player: ClubPlayerRecord, *, lock: bool = False) -> UserRecord:
        if player.user_id is None:
            raise ValueError("摸鱼币场仅限已入职员工")
        query = select(UserRecord).where(UserRecord.id == player.user_id)
        if lock:
            query = query.with_for_update()
        account = session.scalar(query)
        if account is None:
            raise ValueError("摸鱼币场仅限已入职员工")
        return account

    @staticmethod
    def _club_card_active_room(session, player_id: UUID, now: datetime, *, exclude: UUID | None = None) -> Room | None:
        rooms = session.scalars(select(Room).where(
            Room.phase.in_(("waiting", "playing", "hand_finished")),
            Room.updated_at >= now - timedelta(hours=6),
        ).with_for_update()).all()
        raw = str(player_id)
        return next(
            (room for room in rooms if room.id != exclude and raw in room.seats),
            None,
        )

    def _ensure_club_card_player_free(self, session, player_id: UUID, now: datetime, *, exclude: UUID | None = None) -> None:
        active = self._club_card_active_room(session, player_id, now, exclude=exclude)
        if active is not None:
            labels = {"texas": "德州扑克", "zhajinhua": "炸金花", "blackjack": "21 点"}
            raise ValueError(f"你已经在{labels.get(active.game, '其他')}牌桌，请先离开当前房间")
        self._ensure_club_player_available(session, player_id, now)

    @staticmethod
    def _set_club_card_turn_deadline(state: dict, now: datetime) -> dict:
        value = dict(state)
        if value.get("phase") == "playing" and value.get("turn"):
            value["turn_deadline"] = (now + timedelta(seconds=TURN_TIMEOUT_SECONDS)).isoformat()
        else:
            value.pop("turn_deadline", None)
        return value

    def _expire_club_card_turn(self, session, room: Room, now: datetime) -> bool:
        if room.phase != "playing" or not room.state.get("turn"):
            return False
        raw_deadline = room.state.get("turn_deadline")
        if not raw_deadline:
            room.state = self._set_club_card_turn_deadline(room.state, now)
            room.version += 1
            room.updated_at = now
            return True
        try:
            deadline = datetime.fromisoformat(raw_deadline)
        except (TypeError, ValueError):
            deadline = now
        if now < deadline:
            return False
        state = room.state
        turn = state["turn"]
        if room.game == "texas":
            to_call = max(0, state["current_bet"] - state["street_bets"].get(turn, 0))
            action = "fold" if to_call else "check"
        elif room.game == "zhajinhua":
            action = "fold"
        else:
            action = "stand"
        state = apply_action(room.game, state, turn, action, {})
        labels = {"fold": "弃牌", "check": "过牌", "stand": "停牌"}
        state["last_action"] = f"玩家超时，自动{labels[action]}"
        room.state = self._set_club_card_turn_deadline(state, now)
        room.phase = room.state["phase"]
        room.version += 1
        room.updated_at = now
        if room.phase == "hand_finished":
            self._settle_club_card_hand(session, room, now)
        return True

    def create_club_card_room(self, game, platform_id, now, *, room_type, stake, request_id):
        if game not in GAMES:
            raise ValueError("不支持的游戏")
        if room_type not in {"casual", "coin"}:
            raise ValueError("房间类型无效")
        if room_type == "casual":
            stake = 0
        elif stake not in STAKES:
            raise ValueError("摸鱼币场仅支持 5、10、20 币")
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now, lock=True)
                existing = session.scalar(select(Room).where(
                    Room.creator_id == player.id, Room.create_request_id == request_id
                ))
                if existing is not None:
                    return self._club_card_view(session, existing, player)
                self._ensure_club_card_player_free(session, player.id, now)
                if room_type == "coin":
                    self._club_card_account(session, player)
                room = Room(
                    game=game, creator_id=player.id, create_request_id=request_id,
                    seats=[str(player.id)], ready=[], room_type=room_type, stake=stake,
                    state={}, escrowed=[], hand_settled=False, phase="waiting",
                    hand_number=0, version=0, created_at=now, updated_at=now,
                )
                session.add(room); session.flush()
                return self._club_card_view(session, room, player)

    def list_club_card_rooms(self, game, platform_id, now):
        if game not in GAMES:
            raise ValueError("不支持的游戏")
        with self.transaction():
            with self._session() as session:
                viewer = self._club_player(session, platform_id, now)
                rooms = session.scalars(select(Room).where(
                    Room.game == game,
                    Room.phase.in_(("waiting", "playing", "hand_finished")),
                    Room.updated_at >= now - timedelta(hours=6),
                ).order_by(Room.updated_at.desc())).all()
                result = []
                for room in rooms:
                    creator = session.get(ClubPlayerRecord, room.creator_id)
                    result.append({
                        "id": str(room.id), "game": game, "phase": room.phase,
                        "creator_name": creator.display_name if creator else "玩家",
                        "occupied": len(room.seats), "maximum": PLAYER_LIMITS[game][1],
                        "room_type": room.room_type, "stake": room.stake,
                        "mine": str(viewer.id) in room.seats,
                    })
                return result

    def club_card_view(self, game, room_id, platform_id, now):
        with self.transaction():
            with self._session() as session:
                room = self._club_card_room(session, room_id)
                if room.game != game:
                    raise ValueError("房间不存在")
                viewer = self._club_player(session, platform_id, now)
                self._expire_club_card_turn(session, room, now)
                return self._club_card_view(session, room, viewer)

    def _club_card_view(self, session, room: Room, viewer: ClubPlayerRecord) -> dict:
        players = []
        for raw in room.seats:
            player = session.get(ClubPlayerRecord, UUID(raw))
            if player:
                players.append(self._club_player_view(session, player))
        messages = session.execute(
            select(Message, ClubPlayerRecord)
            .join(ClubPlayerRecord, ClubPlayerRecord.id == Message.user_id)
            .where(Message.room_id == room.id)
            .order_by(Message.created_at.desc(), Message.id.desc()).limit(100)
        ).all()
        state = public_view(room.game, room.state, str(viewer.id)) if room.state else {}
        return {
            "id": str(room.id), "game": room.game, "phase": room.phase,
            "creator_id": str(room.creator_id), "room_type": room.room_type,
            "stake": room.stake, "players": players, "ready": room.ready,
            "me": self._club_player_view(session, viewer), "state": state,
            "version": room.version, "hand_number": room.hand_number,
            "messages": [{"id": str(message.id), "player": self._club_player_view(session, player),
                          "text": message.content, "at": message.created_at.isoformat()}
                         for message, player in reversed(messages)],
        }

    def club_card_action(self, game, room_id, platform_id, version, request_id, action, payload, now):
        digest = sha256(json.dumps([action, payload], sort_keys=True).encode()).hexdigest()
        with self.transaction():
            with self._session() as session:
                room = self._club_card_room(session, room_id)
                if room.game != game:
                    raise ValueError("房间不存在")
                player = self._club_player(session, platform_id, now, lock=True)
                receipt = session.scalar(select(Receipt).where(
                    Receipt.room_id == room.id, Receipt.user_id == player.id,
                    Receipt.request_id == request_id,
                ))
                if receipt:
                    if receipt.digest != digest: raise ValueError("重复请求内容不一致")
                    return self._club_card_view(session, room, player)
                timed_out = self._expire_club_card_turn(session, room, now)
                if version != room.version:
                    if timed_out:
                        return self._club_card_view(session, room, player)
                    raise ValueError("牌桌状态已更新，请重试")
                self._apply_club_card_action(session, room, player, action, payload, now)
                room.version += 1; room.updated_at = now
                session.add(Receipt(room_id=room.id, user_id=player.id, request_id=request_id, digest=digest))
                session.flush()
                return self._club_card_view(session, room, player)

    def _apply_club_card_action(self, session, room, player, action, payload, now):
        raw = str(player.id)
        if action == "claim":
            if room.phase not in {"waiting", "hand_finished"}: raise ValueError("请等待本手结束后再上桌")
            if raw in room.seats: return
            self._ensure_club_card_player_free(session, player.id, now, exclude=room.id)
            if len(room.seats) >= PLAYER_LIMITS[room.game][1]: raise ValueError("牌桌已满")
            if room.room_type == "coin": self._club_card_account(session, player)
            room.seats = [*room.seats, raw]
            return
        if action in {"ready", "unready"}:
            if room.phase not in {"waiting", "hand_finished"} or raw not in room.seats: raise ValueError("当前不能准备")
            ready = set(room.ready)
            if action == "ready": ready.add(raw)
            else: ready.discard(raw)
            room.ready = sorted(ready)
            return
        if action == "leave":
            if room.phase not in {"waiting", "hand_finished"}: raise ValueError("牌局中请先完成本手")
            if raw not in room.seats: return
            room.seats = [item for item in room.seats if item != raw]
            room.ready = [item for item in room.ready if item != raw]
            if not room.seats: room.phase = "closed"
            elif player.id == room.creator_id: room.creator_id = UUID(room.seats[0])
            return
        if action == "next":
            if room.phase != "hand_finished" or raw not in room.seats: raise ValueError("当前不能开始下一手")
            room.ready = sorted({*room.ready, raw})
            return
        if action == "start":
            minimum, _ = PLAYER_LIMITS[room.game]
            if room.phase not in {"waiting", "hand_finished"} or player.id != room.creator_id: raise ValueError("只有房主可以开始")
            if len(room.seats) < minimum: raise ValueError(f"至少需要 {minimum} 人")
            if set(room.ready) != set(room.seats): raise ValueError("请等待所有玩家准备")
            if room.room_type == "coin":
                for player_id in room.seats:
                    seated = session.get(ClubPlayerRecord, UUID(player_id))
                    account = self._club_card_account(session, seated, lock=True)
                    if account.balance < room.stake: raise ValueError(f"{seated.display_name} 摸鱼币不足")
                for player_id in room.seats:
                    seated = session.get(ClubPlayerRecord, UUID(player_id))
                    account = self._club_card_account(session, seated, lock=True)
                    self._apply_balance_change(account, -room.stake, f"{room.game}_buy_in", now,
                                               memo=f"{room.game} 第 {room.hand_number + 1} 手入场")
            room.state = self._set_club_card_turn_deadline(
                new_hand(room.game, list(room.seats), room.stake, self._club_card_random),
                now,
            )
            room.ready = []; room.escrowed = list(room.seats); room.hand_settled = False
            room.phase = "playing"; room.hand_number += 1
            return
        if raw not in room.seats:
            raise ValueError("你不在这个牌桌")
        if room.phase != "playing":
            raise ValueError("当前牌局不能操作")
        room.state = self._set_club_card_turn_deadline(
            apply_action(room.game, room.state, raw, action, payload),
            now,
        )
        room.phase = room.state["phase"]
        if room.phase == "hand_finished": self._settle_club_card_hand(session, room, now)

    def _settle_club_card_hand(self, session, room, now):
        if room.hand_settled: return
        if room.room_type == "coin":
            for raw, amount in room.state.get("payouts", {}).items():
                if amount <= 0: continue
                player = session.get(ClubPlayerRecord, UUID(raw))
                account = self._club_card_account(session, player, lock=True)
                self._apply_balance_change(account, int(amount), f"{room.game}_settlement", now,
                                           memo=f"{room.game} 第 {room.hand_number} 手结算")
        if room.game == "blackjack":
            outcomes = {
                raw: "win" if result in {"胜", "并列胜"} else "draw" if "退还" in result else "loss"
                for raw, result in room.state.get("results", {}).items()
            }
        else:
            winners = set(room.state.get("winners", []))
            outcomes = {raw: "win" if raw in winners else "loss" for raw in room.seats}
        session.add(Hand(
            room_id=room.id, game=room.game, hand_number=room.hand_number,
            players=list(room.seats), outcomes=outcomes,
            payouts={raw: int(amount) for raw, amount in room.state.get("payouts", {}).items()},
            created_at=now,
        ))
        room.hand_settled = True
        room.ready = []

    def advance_club_card_deadlines(self, now: datetime) -> int:
        with self.transaction(), self._session() as session:
            rooms = session.scalars(select(Room).where(
                Room.phase == "playing",
            ).with_for_update()).all()
            return sum(self._expire_club_card_turn(session, room, now) for room in rooms)

    def club_card_chat(self, game, room_id, platform_id, request_id, content, now):
        content = content.strip()
        if not content: raise ValueError("请输入消息")
        with self.transaction():
            with self._session() as session:
                room = self._club_card_room(session, room_id, lock=False)
                if room.game != game: raise ValueError("房间不存在")
                player = self._club_player(session, platform_id, now)
                existing = session.scalar(select(Message).where(
                    Message.room_id == room.id, Message.user_id == player.id, Message.request_id == request_id
                ))
                if existing is None:
                    existing = Message(room_id=room.id, user_id=player.id, request_id=request_id,
                                       content=content[:300], created_at=now)
                    session.add(existing); session.flush()
                return {"id": str(existing.id), "player": self._club_player_view(session, player),
                        "text": existing.content, "at": existing.created_at.isoformat()}
