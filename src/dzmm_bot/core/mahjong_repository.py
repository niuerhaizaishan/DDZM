"""Transactional persistence for Club mahjong rooms and coin escrow."""

from datetime import datetime, timedelta
from hashlib import sha256
import json
from secrets import SystemRandom, randbelow
from uuid import UUID, uuid4

from sqlalchemy import select

from .mahjong_state import action_options, apply_action, apply_timeout, new_match
from .schema import (
    ClubPlayerRecord,
    GroupChatRecord,
    InboundRecord,
    MahjongMessageRecord as Message,
    MahjongRequestRecord as Receipt,
    MahjongRoomRecord as Room,
    OutboundRecord,
    UserRecord,
)

COIN_STAKES = {5, 10, 20}


class MahjongRateLimitError(ValueError):
    pass


class MahjongRepositoryMixin:
    _mahjong_random = SystemRandom()

    @staticmethod
    def _mahjong_account(session, player: ClubPlayerRecord, *, lock: bool = False):
        if player.user_id is None:
            raise ValueError("摸鱼币场仅限已入职员工")
        query = select(UserRecord).where(UserRecord.id == player.user_id)
        if lock:
            query = query.with_for_update()
        user = session.scalar(query)
        if user is None:
            raise ValueError("摸鱼币场仅限已入职员工")
        return user

    @staticmethod
    def _mahjong_room(session, room_id: UUID):
        room = session.scalar(select(Room).where(Room.id == room_id).with_for_update())
        if room is None:
            raise ValueError("房间不存在")
        return room

    @staticmethod
    def _mahjong_announced(session, room: Room) -> bool:
        if room.inbound_id is None:
            return True
        return session.scalar(
            select(OutboundRecord.id).where(
                OutboundRecord.inbound_message_id == room.inbound_id,
                OutboundRecord.group_chat_id == room.group_chat_id,
                OutboundRecord.content_type == "text",
                OutboundRecord.status == "sent",
            ).limit(1)
        ) is not None

    def _mahjong_wall(self) -> list[int]:
        return self._mahjong_random.sample(range(136), 136)

    def _mahjong_code(self, session) -> str:
        for _ in range(100):
            code = f"{randbelow(10_000):04d}"
            exists = session.scalar(
                select(Room.id).where(Room.code == code, Room.phase.in_(("waiting", "playing"))).limit(1)
            )
            if exists is None:
                return code
        raise RuntimeError("暂时无法生成入座码")

    def create_mahjong_room(
        self,
        platform_id: str,
        now: datetime,
        *,
        room_type: str = "coin",
        stake: int = 10,
        match_mode: str = "east",
        request_id: UUID,
        group_chat_id: UUID | None = None,
        inbound_id: UUID | None = None,
    ) -> dict:
        if room_type not in {"casual", "coin"}:
            raise ValueError("房间类型无效")
        if room_type == "casual":
            stake = 0
        elif stake not in COIN_STAKES:
            raise ValueError("摸鱼币场仅支持 5、10、20 币")
        if match_mode not in {"east", "south"}:
            raise ValueError("场次类型无效")
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now, lock=True)
                existing = session.scalar(
                    select(Room).where(Room.creator_id == player.id, Room.create_request_id == request_id)
                )
                if existing is not None:
                    return self._mahjong_view(session, existing, player, now)
                self._ensure_club_player_available(session, player.id, now)
                if group_chat_id is not None:
                    inbound = session.scalar(select(InboundRecord).where(InboundRecord.id == inbound_id).with_for_update())
                    group = session.get(GroupChatRecord, group_chat_id)
                    if (
                        inbound is None
                        or inbound.group_chat_id != group_chat_id
                        or inbound.sender_platform_id != platform_id
                        or group is None
                        or not group.listening_enabled
                    ):
                        raise ValueError("群聊或入站消息不可用")
                account = None
                if room_type == "coin":
                    account = self._mahjong_account(session, player, lock=True)
                    if account.balance < stake:
                        raise ValueError(f"创建摸鱼币房需要{stake}摸鱼币")
                room = Room(
                    group_chat_id=group_chat_id,
                    inbound_id=inbound_id,
                    creator_id=player.id,
                    create_request_id=request_id,
                    short_id=uuid4().hex[:12],
                    code=self._mahjong_code(session),
                    room_type=room_type,
                    stake=stake,
                    match_mode=match_mode,
                    seats=[str(player.id), None, None, None],
                    ready=[False, False, False, False],
                    escrowed=[room_type == "coin", False, False, False],
                    presence={},
                    phase="waiting",
                    version=0,
                    settled=False,
                    created_at=now,
                    deadline=now + timedelta(minutes=10),
                )
                session.add(room)
                session.flush()
                if room_type == "coin":
                    self._apply_balance_change(
                        account, -stake, "mahjong_buy_in", now,
                        memo=f"麻将房间 {room.short_id} 入场托管",
                    )
                return self._mahjong_view(session, room, player, now)

    def _mahjong_names(self, session, seats: list) -> list[dict | None]:
        players = []
        for raw_id in seats:
            if raw_id is None:
                players.append(None)
                continue
            user = session.get(ClubPlayerRecord, UUID(raw_id))
            players.append({
                "id": str(user.id) if user else raw_id,
                "name": user.display_name if user else "已离开玩家",
                "employee_number": None,
                "avatar_url": user.avatar_url if user else None,
            })
        return players

    def _mahjong_messages(self, session, room_id: UUID) -> list[dict]:
        rows = session.execute(
            select(Message, ClubPlayerRecord)
            .join(ClubPlayerRecord, ClubPlayerRecord.id == Message.user_id)
            .where(Message.room_id == room_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(100)
        ).all()
        return [
            {"id": str(message.id), "name": player.display_name, "player": self._club_player_view(session, player), "text": message.content, "at": message.created_at.isoformat()}
            for message, player in reversed(rows)
        ]

    def _mahjong_view(self, session, room: Room, user: ClubPlayerRecord, now: datetime) -> dict:
        raw_user = str(user.id)
        seat = room.seats.index(raw_user) if raw_user in room.seats else None
        if seat is not None:
            previous = room.presence.get(str(seat))
            if previous is None or (now - datetime.fromisoformat(previous)).total_seconds() >= 10:
                room.presence = {**room.presence, str(seat): now.isoformat()}
        players = self._mahjong_names(session, room.seats)
        for index, player in enumerate(players):
            if player is not None:
                last_seen = room.presence.get(str(index))
                player.update(
                    ready=room.ready[index],
                    online=bool(last_seen) and (now - datetime.fromisoformat(last_seen)).total_seconds() < 30,
                )
        creator = session.get(ClubPlayerRecord, room.creator_id)
        view = {
            "id": str(room.id),
            "short_id": room.short_id,
            "creator_name": creator.display_name if creator else "玩家",
            "room_type": room.room_type,
            "match_mode": room.match_mode,
            "buy_in": room.stake,
            "prizes": [room.stake * 4, 0, 0, 0] if room.room_type == "coin" else [0, 0, 0, 0],
            "phase": room.phase,
            "version": room.version,
            "seat": seat,
            "creator_seat": 0,
            "players": players,
            "deadline": room.deadline.isoformat() if room.deadline else None,
            "server_time": now.isoformat(),
            "messages": self._mahjong_messages(session, room.id),
            "settlement": room.settlement,
        }
        state = room.state
        if state is None:
            return view
        public = {
            key: deepcopy_value(state[key])
            for key in (
                "mode", "points", "dealer", "round_wind", "hand_number", "honba",
                "riichi_sticks", "turn", "melds", "discards", "riichi", "result",
            )
        }
        public.update(
            remaining=len(state["wall"]) - state.get("live_trim", 0),
            dora_indicators=[state["dead_wall"][index] for index in (4, 6, 8, 10, 12)[: state["kan_count"] + 1]],
            hand=list(state["hands"][seat]) if seat is not None else [],
            hand_counts=[len(hand) for hand in state["hands"]],
            actions=action_options(state, seat) if seat is not None else {},
        )
        if state["phase"] in {"hand_finished", "match_finished"}:
            last_result = state.get("history", [])[-1] if state.get("history") else state.get("result")
            public["last_hand_result"] = last_result
            public["winning_hands"] = {
                str(winner): list(state["hands"][winner])
                for winner in (last_result or {}).get("winners", [])
            }
        view["game"] = public
        return view

    def _settle_mahjong_deadline(self, session, room: Room, now: datetime) -> None:
        if room.phase == "waiting" and room.deadline and now >= room.deadline:
            self._refund_mahjong_room(session, room, now, "房间等待超时")
            room.phase = "cancelled"
            room.deadline = None
            room.version += 1
            return
        if room.state is None or room.phase not in {"playing", "reaction", "hand_finished"}:
            return
        updated = apply_timeout(room.state, now, self._mahjong_wall)
        if updated != room.state:
            room.state = updated
            room.version = updated["version"]
            room.phase = updated["phase"]
            room.deadline = datetime.fromisoformat(updated["deadline"]) if updated.get("deadline") else None
            if room.phase == "match_finished":
                self._settle_mahjong_match(session, room, now)

    def mahjong_view(self, room_id: UUID, platform_id: str, now: datetime) -> dict:
        with self.transaction():
            with self._session() as session:
                room = self._mahjong_room(session, room_id)
                user = self._club_player(session, platform_id, now)
                self._settle_mahjong_deadline(session, room, now)
                return self._mahjong_view(session, room, user, now)

    def list_mahjong_rooms(self, platform_id: str, now: datetime) -> list[dict]:
        with self.transaction():
            with self._session() as session:
                user = self._club_player(session, platform_id, now)
                rooms = session.scalars(
                    select(Room)
                    .where(Room.phase.in_(("waiting", "playing", "reaction", "hand_finished")))
                    .order_by(Room.created_at.desc())
                    .limit(100)
                    .with_for_update()
                ).all()
                result = []
                for room in rooms:
                    self._settle_mahjong_deadline(session, room, now)
                    if room.phase not in {"waiting", "playing", "reaction", "hand_finished"} or not self._mahjong_announced(session, room):
                        continue
                    players = self._mahjong_names(session, room.seats)
                    creator = session.get(ClubPlayerRecord, room.creator_id)
                    result.append({
                        "id": str(room.id),
                        "short_id": room.short_id,
                        "creator_name": creator.display_name if creator else "玩家",
                        "room_type": room.room_type,
                        "stake": room.stake,
                        "match_mode": room.match_mode,
                        "phase": room.phase,
                        "occupied": sum(value is not None for value in room.seats),
                        "mine": str(user.id) in room.seats,
                        "names": [value["name"] for value in players if value],
                    })
                return result

    def _receipt(self, session, room: Room, user: ClubPlayerRecord, request_id: UUID, digest: str):
        previous = session.scalar(
            select(Receipt).where(
                Receipt.room_id == room.id,
                Receipt.user_id == user.id,
                Receipt.request_id == request_id,
            )
        )
        if previous is not None and previous.digest != digest:
            raise ValueError("重复请求的内容不一致")
        return previous

    def mahjong_action(
        self,
        room_id: UUID,
        platform_id: str,
        version: int,
        request_id: UUID,
        action: str,
        payload: dict,
        now: datetime,
    ) -> dict:
        digest = sha256(json.dumps(
            {"version": version, "action": action, "payload": payload},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        with self.transaction():
            with self._session() as session:
                room = self._mahjong_room(session, room_id)
                user = self._club_player(session, platform_id, now, lock=True)
                self._settle_mahjong_deadline(session, room, now)
                previous = self._receipt(session, room, user, request_id, digest)
                if previous is not None:
                    return self._mahjong_view(session, room, user, now)
                if version != room.version:
                    raise ValueError("房间已更新，请刷新")
                if room.phase == "waiting":
                    self._mahjong_waiting_action(session, room, user, action, payload, now)
                elif room.phase == "match_finished":
                    raw_user = str(user.id)
                    if raw_user not in room.seats:
                        raise ValueError("观众不能操作席位")
                    seat = room.seats.index(raw_user)
                    if action in {"ready", "unready"}:
                        ready = list(room.ready)
                        ready[seat] = action == "ready"
                        room.ready = ready
                        room.version += 1
                    elif action == "start":
                        if seat != 0:
                            raise ValueError("只有房主可以开始下一场")
                        if not all(room.ready):
                            raise ValueError("请等待所有玩家准备")
                        if room.room_type == "coin":
                            accounts = []
                            for raw_player_id in room.seats:
                                player = session.get(ClubPlayerRecord, UUID(raw_player_id))
                                account = self._mahjong_account(session, player, lock=True)
                                if account.balance < room.stake:
                                    raise ValueError(f"{player.display_name}余额不足，无法续场")
                                accounts.append(account)
                            for account in accounts:
                                self._apply_balance_change(
                                    account, -room.stake, "mahjong_buy_in", now,
                                    memo=f"麻将房间 {room.short_id} 续场托管",
                                )
                        state = new_match(self._mahjong_wall(), now, mode=room.match_mode)
                        state["version"] = room.version + 1
                        room.state = state
                        room.phase = state["phase"]
                        room.version = state["version"]
                        room.deadline = datetime.fromisoformat(state["deadline"])
                        room.ready = [False, False, False, False]
                        room.escrowed = [room.room_type == "coin"] * 4
                        room.settled, room.settlement = False, None
                    else:
                        raise ValueError("终局结算不支持该操作")
                elif room.phase in {"playing", "reaction", "hand_finished"}:
                    if action == "leave":
                        raise ValueError("牌局进行中不能离席，断线后将自动摸切")
                    if room.state is None:
                        raise RuntimeError("麻将状态缺失")
                    state_payload = {**payload, "version": version}
                    room.state = apply_action(room.state, room.seats.index(str(user.id)), action, state_payload, now)
                    room.version = room.state["version"]
                    room.phase = room.state["phase"]
                    room.deadline = datetime.fromisoformat(room.state["deadline"]) if room.state.get("deadline") else None
                    if room.phase == "match_finished":
                        self._settle_mahjong_match(session, room, now)
                else:
                    raise ValueError("房间已经结束")
                session.add(Receipt(
                    room_id=room.id, user_id=user.id, request_id=request_id,
                    digest=digest, created_at=now,
                ))
                session.flush()
                return self._mahjong_view(session, room, user, now)

    def _mahjong_waiting_action(self, session, room: Room, user: ClubPlayerRecord, action: str, payload: dict, now: datetime) -> None:
        raw_user = str(user.id)
        seat = room.seats.index(raw_user) if raw_user in room.seats else None
        if action == "claim":
            if seat is not None:
                return
            self._ensure_club_player_available(
                session, user.id, now, exclude=("mahjong", room.id),
            )
            if room.deadline is None or now >= room.deadline:
                raise ValueError("房间已过期")
            try:
                seat = room.seats.index(None)
            except ValueError as error:
                raise ValueError("房间已满") from error
            if room.room_type == "coin":
                account = self._mahjong_account(session, user, lock=True)
                if account.balance < room.stake:
                    raise ValueError(f"余额不足，需要{room.stake}摸鱼币")
                self._apply_balance_change(
                    account, -room.stake, "mahjong_buy_in", now,
                    memo=f"麻将房间 {room.short_id} 入场托管",
                )
            seats, escrowed = list(room.seats), list(room.escrowed)
            seats[seat], escrowed[seat] = raw_user, room.room_type == "coin"
            room.seats, room.escrowed = seats, escrowed
        elif action in {"ready", "unready"}:
            if seat is None:
                raise ValueError("请先入座")
            ready = list(room.ready)
            ready[seat] = action == "ready"
            room.ready = ready
        elif action == "leave":
            if seat is None:
                return
            if seat == 0:
                self._refund_mahjong_room(session, room, now, "房主取消房间")
                room.phase, room.deadline = "cancelled", None
            else:
                self._refund_mahjong_seat(session, room, seat, now, "离开等待房间")
                seats, ready, escrowed = list(room.seats), list(room.ready), list(room.escrowed)
                seats[seat], ready[seat], escrowed[seat] = None, False, False
                room.seats, room.ready, room.escrowed = seats, ready, escrowed
        elif action == "start":
            if seat != 0:
                raise ValueError("只有房主可以开始")
            if any(value is None for value in room.seats) or not all(room.ready):
                raise ValueError("需要四人全部准备")
            state = new_match(self._mahjong_wall(), now, mode=room.match_mode)
            state["version"] = room.version + 1
            room.state = state
            room.phase = state["phase"]
            room.version = state["version"]
            room.deadline = datetime.fromisoformat(state["deadline"])
            return
        else:
            raise ValueError("等待阶段不支持该操作")
        room.version += 1

    def _refund_mahjong_seat(self, session, room: Room, seat: int, now: datetime, reason: str) -> None:
        if not room.escrowed[seat] or room.seats[seat] is None:
            return
        player = session.get(ClubPlayerRecord, UUID(room.seats[seat]))
        user = session.get(UserRecord, player.user_id, with_for_update=True) if player and player.user_id else None
        if user is not None:
            self._apply_balance_change(
                user, room.stake, "mahjong_refund", now,
                memo=f"麻将房间 {room.short_id}：{reason}",
            )

    def _refund_mahjong_room(self, session, room: Room, now: datetime, reason: str) -> None:
        for seat in range(4):
            self._refund_mahjong_seat(session, room, seat, now, reason)
        room.escrowed = [False, False, False, False]
        room.ready = [False, False, False, False]

    def _settle_mahjong_match(self, session, room: Room, now: datetime) -> None:
        if room.settled or room.state is None or room.state["phase"] != "match_finished":
            return
        order = room.state["result"]["order"]
        payouts = [0, 0, 0, 0]
        top_score = max(room.state["points"])
        winner_seats = [seat for seat in order if room.state["points"][seat] == top_score]
        if room.room_type == "coin":
            if not all(room.escrowed):
                raise RuntimeError("麻将奖池托管不完整")
            pot = room.stake * 4
            for winner_index, seat in enumerate(winner_seats):
                player = session.get(ClubPlayerRecord, UUID(room.seats[seat]))
                user = session.get(UserRecord, player.user_id, with_for_update=True) if player and player.user_id else None
                if user is None:
                    raise RuntimeError("麻将结算玩家不存在")
                payout = pot // len(winner_seats) + (1 if winner_index < pot % len(winner_seats) else 0)
                payouts[seat] = payout
                self._apply_balance_change(
                    user, payout, "mahjong_settlement", now,
                    memo=f"麻将房间 {room.short_id} 胜方结算",
                )
        room.escrowed = [False, False, False, False]
        room.settled = True
        room.settlement = {
            "order": order,
            "payouts": payouts,
            "points": room.state["points"],
            "winner_seats": winner_seats,
            "outcomes": ["win" if seat in winner_seats else "loss" for seat in range(4)],
        }
        room.phase = "match_finished"
        room.deadline = None

    def mahjong_chat(self, room_id: UUID, platform_id: str, request_id: UUID, content: str, now: datetime) -> dict:
        content = content.strip()
        if not content:
            raise ValueError("请输入消息")
        with self.transaction():
            with self._session() as session:
                room = self._mahjong_room(session, room_id)
                user = self._club_player(session, platform_id, now)
                previous = session.scalar(select(Message).where(
                    Message.room_id == room.id, Message.user_id == user.id, Message.request_id == request_id,
                ))
                if previous is not None:
                    return {"id": str(previous.id), "name": user.display_name, "text": previous.content}
                latest = session.scalar(
                    select(Message.created_at)
                    .where(Message.room_id == room.id, Message.user_id == user.id)
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
                if latest and (now - latest).total_seconds() < 2:
                    raise MahjongRateLimitError("请间隔两秒再发言")
                message = Message(
                    room_id=room.id, user_id=user.id, request_id=request_id,
                    content=content, created_at=now,
                )
                session.add(message)
                session.flush()
                return {"id": str(message.id), "name": user.display_name, "text": message.content}

    def advance_mahjong_deadlines(self, now: datetime) -> int:
        changed = 0
        with self.transaction():
            with self._session() as session:
                rooms = session.scalars(
                    select(Room)
                    .where(Room.deadline.is_not(None), Room.deadline <= now)
                    .with_for_update(skip_locked=True)
                ).all()
                for room in rooms:
                    before = room.version
                    self._settle_mahjong_deadline(session, room, now)
                    changed += room.version != before
        return changed


def deepcopy_value(value):
    # Kept local to avoid leaking mutable JSON objects into FastAPI encoding.
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, ensure_ascii=False))
    return value
