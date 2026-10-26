"""Shared Club identity, social features, and task rewards."""

from datetime import datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select

from .bot_accounts import is_bot_platform_id
from .club_card_games import PLAYER_LIMITS
from .schema import (
    BalanceTransactionRecord,
    ClubDirectMessageRecord,
    ClubFriendshipRecord,
    ClubPlayerRecord,
    ClubPublicMessageRecord,
    ClubTaskClaimRecord,
    ClubCardRoomRecord,
    ClubCardHandRecord,
    ChessGameRecord,
    DailyCheckinRecord,
    DarkMarketListingRecord,
    DoudizhuRoomRecord,
    DoudizhuRoundRecord,
    DrawguessRoomRecord,
    InboundRecord,
    MahjongRoomRecord,
    RandomEventParticipantRecord,
    BEIJING,
    UserRecord,
)


TASK_REWARDS = {
    "employment": 20,
    "checkin": 2,
    "random_event": 3,
    "five_rounds": 3,
    "activity": 5,
    "dark_market": 3,
}
DAILY_TASKS = frozenset(TASK_REWARDS) - {"employment"}
CLUB_TRANSACTION_LABELS = {
    "club_task_reward": "任务奖励",
    "mahjong_buy_in": "麻将入场",
    "mahjong_refund": "麻将退款",
    "mahjong_settlement": "麻将结算",
    "chess_buy_in": "象棋入场",
    "chess_refund": "象棋退款",
    "chess_settlement": "象棋结算",
    "doudizhu_buy_in": "斗地主入场",
    "doudizhu_refund": "斗地主退款",
    "doudizhu_settlement": "斗地主结算",
    "drawguess_buy_in": "你画我猜入场",
    "drawguess_refund": "你画我猜退款",
    "drawguess_settlement": "你画我猜结算",
    "texas_buy_in": "德州扑克入场",
    "texas_settlement": "德州扑克结算",
    "zhajinhua_buy_in": "炸金花入场",
    "zhajinhua_settlement": "炸金花结算",
    "blackjack_buy_in": "21 点入场",
    "blackjack_settlement": "21 点结算",
}


class ClubRateLimitError(ValueError):
    pass


class ClubRepositoryMixin:
    @staticmethod
    def _club_platform_id(platform_id: str) -> str:
        if (
            not isinstance(platform_id, str)
            or not platform_id
            or len(platform_id) > 255
            or any(char.isspace() for char in platform_id)
        ):
            raise ValueError("无法读取玩家身份")
        return platform_id

    def _club_player(
        self,
        session,
        platform_id: str,
        now: datetime,
        *,
        display_name: str | None = None,
        avatar_url: str | None = None,
        lock: bool = False,
    ) -> ClubPlayerRecord:
        platform_id = self._club_platform_id(platform_id)
        query = select(ClubPlayerRecord).where(
            ClubPlayerRecord.platform_id == platform_id
        )
        if lock:
            query = query.with_for_update()
        player = session.scalar(query)
        employee = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == platform_id)
        )
        if player is None:
            player = ClubPlayerRecord(
                id=employee.id if employee is not None else uuid4(),
                platform_id=platform_id,
                display_name=(display_name or (employee.display_name if employee else None) or f"玩家{platform_id[:6]}")[:64],
                avatar_url=avatar_url or (employee.profile_image_url if employee else None),
                user_id=employee.id if employee else None,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(player)
            session.flush()
            return player
        changed = False
        if employee is not None and player.user_id != employee.id:
            player.user_id = employee.id
            changed = True
        next_name = display_name or (employee.display_name if employee else None)
        if next_name and player.display_name != next_name[:64]:
            player.display_name = next_name[:64]
            changed = True
        if avatar_url and player.avatar_url != avatar_url:
            player.avatar_url = avatar_url
            changed = True
        if changed:
            player.updated_at = now
        return player

    def club_presence(self, platform_id: str, now: datetime) -> dict[str, int]:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now, lock=True)
                player.last_seen_at = now
                cutoff = now - timedelta(seconds=30)
                online_ids = set(session.scalars(
                    select(ClubPlayerRecord.id).where(
                        ClubPlayerRecord.last_seen_at >= cutoff
                    )
                ))
                playing_ids: set[UUID] = set()
                for game in session.scalars(
                    select(ChessGameRecord).where(ChessGameRecord.status == "playing")
                ):
                    playing_ids.update(
                        value for value in (game.red_user_id, game.black_user_id) if value
                    )
                for room in session.scalars(
                    select(DoudizhuRoomRecord).where(
                        DoudizhuRoomRecord.phase.in_(("bidding", "playing"))
                    )
                ):
                    playing_ids.update(UUID(value) for value in room.seats if value)
                for room in session.scalars(
                    select(DrawguessRoomRecord).where(
                        DrawguessRoomRecord.phase.in_(("selecting", "drawing", "revealing"))
                    )
                ):
                    playing_ids.update(
                        UUID(value) for value in (room.state or {}).get("seats", []) if value
                    )
                for room in session.scalars(
                    select(MahjongRoomRecord).where(
                        MahjongRoomRecord.phase.in_(("playing", "reaction", "hand_finished"))
                    )
                ):
                    playing_ids.update(UUID(value) for value in room.seats if value)
                for room in session.scalars(
                    select(ClubCardRoomRecord).where(ClubCardRoomRecord.phase == "playing")
                ):
                    playing_ids.update(UUID(value) for value in room.seats if value)
                return {
                    "online": len(online_ids),
                    "playing": len(online_ids & playing_ids),
                }

    def _club_active_room_candidate(self, session, player_id: UUID, now: datetime, *, exclude: tuple[str, UUID] | None = None):
        raw = str(player_id)
        candidates = []

        def add(game, room, phase, created_at):
            if exclude == (game, room.id):
                return
            priority = 1 if phase not in {"waiting", "hand_finished", "finished"} else 0
            candidates.append((priority, created_at, game, room, phase))

        for room in session.scalars(select(ClubCardRoomRecord).where(
            ClubCardRoomRecord.phase.in_(("waiting", "playing", "hand_finished")),
            ClubCardRoomRecord.updated_at >= now - timedelta(hours=6),
        )):
            if raw in room.seats:
                add(room.game, room, room.phase, room.updated_at)
        for room in session.scalars(select(MahjongRoomRecord).where(
            MahjongRoomRecord.phase.in_(("waiting", "playing", "reaction", "hand_finished")),
        )):
            self._settle_mahjong_deadline(session, room, now)
            if room.phase in {"waiting", "playing", "reaction", "hand_finished"} and raw in room.seats:
                add("mahjong", room, room.phase, room.created_at)
        for room in session.scalars(select(DoudizhuRoomRecord).where(
            DoudizhuRoomRecord.phase.in_(("waiting", "bidding", "playing")),
        )):
            if raw in room.seats and (room.phase != "waiting" or room.deadline is None or room.deadline > now):
                add("doudizhu", room, room.phase, room.created_at)
        for room in session.scalars(select(DrawguessRoomRecord).where(
            DrawguessRoomRecord.phase.in_(("waiting", "selecting", "drawing", "revealing")),
        )):
            if raw in (room.state or {}).get("seats", []) and (room.phase != "waiting" or room.deadline is None or room.deadline > now):
                add("drawguess", room, room.phase, room.created_at)
        for room in session.scalars(select(ChessGameRecord).where(
            ChessGameRecord.status.in_(("waiting", "playing")),
        )):
            participants = {
                room.creator_user_id, room.opponent_user_id,
                room.red_user_id, room.black_user_id,
            }
            if player_id in participants and (room.status != "waiting" or room.claim_deadline > now):
                add("chess", room, room.status, room.created_at)
        return max(candidates, key=lambda item: (item[0], item[1])) if candidates else None

    def _ensure_club_player_available(self, session, player_id: UUID, now: datetime, *, exclude: tuple[str, UUID] | None = None) -> None:
        active = self._club_active_room_candidate(session, player_id, now, exclude=exclude)
        if active is None:
            return
        labels = {
            "mahjong": "摸鱼麻将", "chess": "群聊象棋", "doudizhu": "斗地主",
            "drawguess": "你画我猜", "texas": "德州扑克", "zhajinhua": "炸金花",
            "blackjack": "21 点",
        }
        raise ValueError(f"你已经在{labels[active[2]]}房间，请先离开当前房间")

    def club_active_room(self, platform_id: str, now: datetime) -> dict | None:
        with self.transaction(), self._session() as session:
            player = self._club_player(session, platform_id, now)
            active = self._club_active_room_candidate(session, player.id, now)
            if active is None:
                return None
            _, _, game, room, phase = active
            if game in {"texas", "zhajinhua", "blackjack"}:
                self._expire_club_card_turn(session, room, now)
                phase = room.phase
            return {"game": game, "room_id": str(room.id), "phase": phase}

    def ensure_club_player(
        self,
        platform_id: str,
        now: datetime,
        *,
        display_name: str | None = None,
        avatar_url: str | None = None,
    ) -> dict:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(
                    session,
                    platform_id,
                    now,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    lock=True,
                )
                player.last_seen_at = now
                return self._club_player_view(session, player)

    def club_room_status(
        self, game: str, room_id: UUID, platform_id: str, now: datetime
    ) -> dict:
        capacities = {
            "mahjong": 4,
            "chess": 2,
            "doudizhu": 3,
            "drawguess": 8,
            **{key: maximum for key, (_, maximum) in PLAYER_LIMITS.items()},
        }
        if game not in capacities:
            raise ValueError("不支持的游戏")

        with self.transaction(), self._session() as session:
            self._club_player(session, platform_id, now)
            room = None
            phase = "closed"
            occupied = 0
            if game == "mahjong":
                room = session.get(MahjongRoomRecord, room_id)
                if room is not None:
                    self._settle_mahjong_deadline(session, room, now)
                    phase = room.phase
                    occupied = sum(value is not None for value in room.seats)
            elif game == "chess":
                room = session.get(ChessGameRecord, room_id)
                if room is not None:
                    phase = "cancelled" if (
                        room.status == "waiting" and now >= room.claim_deadline
                    ) else room.status
                    occupied = 1 + int(room.opponent_user_id is not None)
            elif game == "doudizhu":
                room = session.get(DoudizhuRoomRecord, room_id)
                if room is not None:
                    phase = "cancelled" if (
                        room.phase == "waiting" and room.deadline and now >= room.deadline
                    ) else room.phase
                    occupied = sum(value is not None for value in room.seats)
            elif game == "drawguess":
                room = session.get(DrawguessRoomRecord, room_id)
                if room is not None:
                    self._dg_advance(session, room, now)
                    phase = room.phase
                    occupied = len((room.state or {}).get("seats", []))
            else:
                room = session.get(ClubCardRoomRecord, room_id)
                if room is not None and room.game == game:
                    phase = "closed" if room.updated_at < now - timedelta(hours=6) else room.phase
                    occupied = len(room.seats)
                elif room is not None:
                    room = None

            if room is None or phase in {"closed", "cancelled"}:
                state, label = "dissolved", "已解散"
            elif phase in {"finished", "match_finished"}:
                state, label = "finished", "已结束"
            elif phase == "waiting":
                state, label = "waiting", "候场"
            else:
                state, label = "started", "已开始"
            return {
                "game": game,
                "room_id": str(room_id),
                "state": state,
                "label": label,
                "occupied": occupied,
                "capacity": capacities[game],
                "enterable": state in {"waiting", "started"},
            }

    @staticmethod
    def _club_player_view(session, player: ClubPlayerRecord) -> dict:
        employee = session.get(UserRecord, player.user_id) if player.user_id else None
        return {
            "id": str(player.id),
            "uid": player.platform_id,
            "name": player.display_name,
            "avatar_url": player.avatar_url,
            "employee": employee is not None,
            "balance": int(employee.balance) if employee is not None else None,
        }

    def club_profile(self, platform_id: str, now: datetime) -> dict:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                recent_transactions = []
                if player.user_id is not None:
                    recent_transactions = [
                        {
                            "id": str(row.id),
                            "amount": row.amount,
                            "label": CLUB_TRANSACTION_LABELS.get(
                                row.source, row.memo or row.source
                            ),
                            "at": row.occurred_at.isoformat(),
                        }
                        for row in session.scalars(
                            select(BalanceTransactionRecord)
                            .where(BalanceTransactionRecord.user_id == player.user_id)
                            .order_by(
                                BalanceTransactionRecord.occurred_at.desc(),
                                BalanceTransactionRecord.id.desc(),
                            )
                            .limit(10)
                        )
                    ]
                return {
                    **self._club_player_view(session, player),
                    "stats": self._club_game_stats(session, player),
                    "recent_transactions": recent_transactions,
                }

    def club_player_profile(self, platform_id: str, target_player_id: UUID, now: datetime) -> dict:
        with self.transaction():
            with self._session() as session:
                viewer = self._club_player(session, platform_id, now)
                target = session.get(ClubPlayerRecord, target_player_id)
                if target is None:
                    raise ValueError("玩家不存在")
                friendship = self._club_friendship(session, viewer.id, target.id) if viewer.id != target.id else None
                relation = "self" if viewer.id == target.id else (
                    "friend" if friendship and friendship.status == "accepted" else
                    "incoming" if friendship and friendship.recipient_id == viewer.id else
                    "outgoing" if friendship else "none"
                )
                return {**self._club_player_view(session, target), "relationship": relation}

    @staticmethod
    def _club_game_stats(session, player: ClubPlayerRecord) -> dict:
        totals = {"played": 0, "wins": 0, "losses": 0, "draws": 0}
        games = {
            key: {"played": 0, "wins": 0, "losses": 0, "draws": 0}
            for key in ("mahjong", "chess", "doudizhu", "drawguess", "texas", "zhajinhua", "blackjack")
        }

        def record(game: str, outcome: str | None) -> None:
            if outcome not in {"win", "loss", "draw"}:
                return
            field = {"win": "wins", "loss": "losses", "draw": "draws"}[outcome]
            games[game]["played"] += 1
            games[game][field] += 1
            totals["played"] += 1
            totals[field] += 1

        for room in session.scalars(
            select(ChessGameRecord).where(
                ChessGameRecord.settled.is_(True),
                or_(
                    ChessGameRecord.red_user_id == player.id,
                    ChessGameRecord.black_user_id == player.id,
                ),
            )
        ):
            side = "red" if room.red_user_id == player.id else "black"
            record("chess", (room.settlement or {}).get("outcomes", {}).get(side))

        raw_id = str(player.id)
        for game, model, seats_getter in (
            ("doudizhu", DoudizhuRoomRecord, lambda room: room.seats),
            ("drawguess", DrawguessRoomRecord, lambda room: (room.state or {}).get("seats", [])),
            ("mahjong", MahjongRoomRecord, lambda room: room.seats),
        ):
            for room in session.scalars(select(model).where(model.settled.is_(True))):
                seats = seats_getter(room)
                if raw_id not in seats:
                    continue
                seat = seats.index(raw_id)
                outcomes = (room.settlement or {}).get("outcomes", [])
                record(game, outcomes[seat] if seat < len(outcomes) else None)

        for hand in session.scalars(select(ClubCardHandRecord)):
            if raw_id in hand.players:
                record(hand.game, hand.outcomes.get(raw_id))

        return {"total": totals, "games": games}

    def club_public_messages(self, platform_id: str, now: datetime) -> list[dict]:
        with self.transaction():
            with self._session() as session:
                self._club_player(session, platform_id, now)
                rows = session.execute(
                    select(ClubPublicMessageRecord, ClubPlayerRecord)
                    .join(ClubPlayerRecord, ClubPlayerRecord.id == ClubPublicMessageRecord.player_id)
                    .order_by(ClubPublicMessageRecord.created_at.desc(), ClubPublicMessageRecord.id.desc())
                    .limit(100)
                ).all()
                return [
                    {
                        "id": str(message.id),
                        "player": self._club_player_view(session, player),
                        "text": message.content,
                        "at": message.created_at.isoformat(),
                    }
                    for message, player in reversed(rows)
                ]

    def club_social_version(self, platform_id: str, now: datetime) -> dict[str, str]:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                public_count = session.scalar(select(func.count(ClubPublicMessageRecord.id)))
                public = session.execute(
                    select(ClubPublicMessageRecord.id, ClubPublicMessageRecord.created_at)
                    .order_by(ClubPublicMessageRecord.created_at.desc(), ClubPublicMessageRecord.id.desc())
                    .limit(1)
                ).first()
                direct_filter = or_(
                    ClubDirectMessageRecord.sender_id == player.id,
                    ClubDirectMessageRecord.recipient_id == player.id,
                )
                direct_count = session.scalar(
                    select(func.count(ClubDirectMessageRecord.id)).where(direct_filter)
                )
                direct = session.execute(
                    select(ClubDirectMessageRecord.id, ClubDirectMessageRecord.created_at)
                    .where(direct_filter)
                    .order_by(ClubDirectMessageRecord.created_at.desc(), ClubDirectMessageRecord.id.desc())
                    .limit(1)
                ).first()
                friendship_filter = or_(
                    ClubFriendshipRecord.requester_id == player.id,
                    ClubFriendshipRecord.recipient_id == player.id,
                )
                friendship_count = session.scalar(
                    select(func.count(ClubFriendshipRecord.id)).where(friendship_filter)
                )
                friendship = session.execute(
                    select(
                        ClubFriendshipRecord.id,
                        ClubFriendshipRecord.updated_at,
                        ClubFriendshipRecord.status,
                    )
                    .where(friendship_filter)
                    .order_by(ClubFriendshipRecord.updated_at.desc(), ClubFriendshipRecord.id.desc())
                    .limit(1)
                ).first()

                def token(row, count: int, *, include_status: bool = False) -> str:
                    if not row:
                        return ""
                    status = f":{row[2]}" if include_status else ""
                    return f"{count}:{row[1].isoformat()}:{row[0]}{status}"

                return {
                    "channel": token(public, public_count),
                    "direct": token(direct, direct_count),
                    "friends": token(friendship, friendship_count, include_status=True),
                }

    def send_club_public_message(
        self, platform_id: str, content: str, now: datetime
    ) -> dict:
        content = content.strip()
        if not content:
            raise ValueError("请输入消息")
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                latest = session.scalar(
                    select(ClubPublicMessageRecord.created_at)
                    .where(ClubPublicMessageRecord.player_id == player.id)
                    .order_by(ClubPublicMessageRecord.created_at.desc())
                    .limit(1)
                )
                if latest and (now - latest).total_seconds() < 2:
                    raise ClubRateLimitError("请间隔两秒再发言")
                message = ClubPublicMessageRecord(
                    player_id=player.id,
                    content=content[:300],
                    created_at=now,
                )
                session.add(message)
                session.flush()
                return {
                    "id": str(message.id),
                    "player": self._club_player_view(session, player),
                    "text": message.content,
                    "at": now.isoformat(),
                }

    @staticmethod
    def _club_friendship(session, left: UUID, right: UUID):
        return session.scalar(
            select(ClubFriendshipRecord).where(
                or_(
                    and_(
                        ClubFriendshipRecord.requester_id == left,
                        ClubFriendshipRecord.recipient_id == right,
                    ),
                    and_(
                        ClubFriendshipRecord.requester_id == right,
                        ClubFriendshipRecord.recipient_id == left,
                    ),
                )
            )
        )

    def club_friends(self, platform_id: str, now: datetime) -> dict:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                rows = session.scalars(
                    select(ClubFriendshipRecord).where(
                        or_(
                            ClubFriendshipRecord.requester_id == player.id,
                            ClubFriendshipRecord.recipient_id == player.id,
                        )
                    ).order_by(ClubFriendshipRecord.updated_at.desc())
                ).all()
                result = {"friends": [], "incoming": [], "outgoing": []}
                for row in rows:
                    other_id = row.recipient_id if row.requester_id == player.id else row.requester_id
                    other = session.get(ClubPlayerRecord, other_id)
                    if other is None:
                        continue
                    view = self._club_player_view(session, other)
                    if row.status == "accepted":
                        result["friends"].append(view)
                    elif row.recipient_id == player.id:
                        result["incoming"].append({**view, "request_id": str(row.id)})
                    else:
                        result["outgoing"].append(view)
                return result

    def request_club_friend(
        self, platform_id: str, target_player_id: UUID, now: datetime
    ) -> dict:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                target = session.get(ClubPlayerRecord, target_player_id)
                if target is None:
                    raise ValueError("玩家不存在")
                if target.id == player.id:
                    raise ValueError("不能添加自己")
                existing = self._club_friendship(session, player.id, target.id)
                if existing is None:
                    existing = ClubFriendshipRecord(
                        requester_id=player.id,
                        recipient_id=target.id,
                        status="pending",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(existing)
                elif existing.status == "accepted":
                    return self._club_player_view(session, target)
                elif existing.recipient_id == player.id:
                    existing.status = "accepted"
                    existing.updated_at = now
                session.flush()
                return self._club_player_view(session, target)

    def accept_club_friend(
        self, platform_id: str, request_id: UUID, now: datetime
    ) -> dict:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                request = session.scalar(
                    select(ClubFriendshipRecord).where(
                        ClubFriendshipRecord.id == request_id,
                        ClubFriendshipRecord.recipient_id == player.id,
                        ClubFriendshipRecord.status == "pending",
                    ).with_for_update()
                )
                if request is None:
                    raise ValueError("好友申请不存在")
                request.status = "accepted"
                request.updated_at = now
                other = session.get(ClubPlayerRecord, request.requester_id)
                return self._club_player_view(session, other)

    def club_direct_messages(
        self, platform_id: str, target_player_id: UUID, now: datetime
    ) -> list[dict]:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                friendship = self._club_friendship(session, player.id, target_player_id)
                if friendship is None or friendship.status != "accepted":
                    raise ValueError("仅好友可以私聊")
                rows = session.scalars(
                    select(ClubDirectMessageRecord)
                    .where(
                        or_(
                            and_(
                                ClubDirectMessageRecord.sender_id == player.id,
                                ClubDirectMessageRecord.recipient_id == target_player_id,
                            ),
                            and_(
                                ClubDirectMessageRecord.sender_id == target_player_id,
                                ClubDirectMessageRecord.recipient_id == player.id,
                            ),
                        )
                    )
                    .order_by(ClubDirectMessageRecord.created_at.desc())
                    .limit(100)
                ).all()
                return [
                    {
                        "id": str(message.id),
                        "mine": message.sender_id == player.id,
                        "text": message.content,
                        "at": message.created_at.isoformat(),
                    }
                    for message in reversed(rows)
                ]

    def send_club_direct_message(
        self,
        platform_id: str,
        target_player_id: UUID,
        content: str,
        now: datetime,
    ) -> dict:
        content = content.strip()
        if not content:
            raise ValueError("请输入消息")
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                friendship = self._club_friendship(session, player.id, target_player_id)
                if friendship is None or friendship.status != "accepted":
                    raise ValueError("仅好友可以私聊")
                latest = session.scalar(
                    select(ClubDirectMessageRecord.created_at)
                    .where(ClubDirectMessageRecord.sender_id == player.id)
                    .order_by(ClubDirectMessageRecord.created_at.desc())
                    .limit(1)
                )
                if latest and (now - latest).total_seconds() < 2:
                    raise ClubRateLimitError("请间隔两秒再发言")
                message = ClubDirectMessageRecord(
                    sender_id=player.id,
                    recipient_id=target_player_id,
                    content=content[:300],
                    created_at=now,
                )
                session.add(message)
                session.flush()
                return {
                    "id": str(message.id),
                    "mine": True,
                    "text": message.content,
                    "at": now.isoformat(),
                }

    @staticmethod
    def _club_five_rounds(
        session,
        player: ClubPlayerRecord,
        day_start: datetime,
        day_end: datetime,
    ) -> bool:
        raw_id = str(player.id)
        for room in session.scalars(select(DoudizhuRoomRecord).where(
            DoudizhuRoomRecord.created_at >= day_start,
            DoudizhuRoomRecord.created_at < day_end,
        )):
            if raw_id not in room.seats:
                continue
            completed = sum(
                (round_row.state or {}).get("phase") == "finished"
                for round_row in session.scalars(select(DoudizhuRoundRecord).where(
                    DoudizhuRoundRecord.room_id == room.id,
                ))
            )
            if completed >= 5:
                return True
        for room in session.scalars(select(DrawguessRoomRecord).where(
            DrawguessRoomRecord.created_at >= day_start,
            DrawguessRoomRecord.created_at < day_end,
        )):
            state = room.state or {}
            if raw_id in state.get("seats", []) and int(state.get("turn_index", 0)) >= 5:
                return True
        for room in session.scalars(select(MahjongRoomRecord).where(
            MahjongRoomRecord.created_at >= day_start,
            MahjongRoomRecord.created_at < day_end,
        )):
            state = room.state or {}
            completed_hands = max(0, int(state.get("round_wind", 27)) - 27) * 4
            completed_hands += max(0, int(state.get("hand_number", 1)) - 1)
            if raw_id in room.seats and completed_hands >= 5:
                return True
        return False

    def _club_task_eligibility(
        self,
        session,
        player: ClubPlayerRecord,
        now: datetime,
    ) -> dict[str, bool]:
        if player.user_id is None or is_bot_platform_id(player.platform_id):
            return {key: False for key in TASK_REWARDS}
        user_id = player.user_id
        today = now.astimezone(BEIJING).date()
        day_start = datetime.combine(today, time.min, tzinfo=BEIJING)
        day_end = day_start + timedelta(days=1)
        activity = session.execute(
            select(func.count(InboundRecord.id), func.coalesce(func.sum(func.length(InboundRecord.content)), 0)).where(
                InboundRecord.sender_platform_id == player.platform_id,
                InboundRecord.source_type == "group",
                InboundRecord.content_type == "text",
                InboundRecord.received_at >= day_start,
                InboundRecord.received_at < day_end,
                ~InboundRecord.content.startswith("/"),
            )
        ).one()
        return {
            "employment": True,
            "checkin": session.scalar(
                select(DailyCheckinRecord.id).where(
                    DailyCheckinRecord.user_id == user_id,
                    DailyCheckinRecord.checkin_date == today,
                ).limit(1)
            ) is not None,
            "random_event": session.scalar(
                select(RandomEventParticipantRecord.id).where(
                    RandomEventParticipantRecord.user_id == user_id,
                    RandomEventParticipantRecord.rounds > 0,
                    RandomEventParticipantRecord.joined_at >= day_start,
                    RandomEventParticipantRecord.joined_at < day_end,
                ).limit(1)
            ) is not None,
            "five_rounds": self._club_five_rounds(
                session, player, day_start, day_end
            ),
            "activity": int(activity[0]) >= 20 and int(activity[1]) > 300,
            "dark_market": session.scalar(
                select(DarkMarketListingRecord.id).where(
                    DarkMarketListingRecord.seller_user_id == user_id,
                    DarkMarketListingRecord.created_at >= day_start,
                    DarkMarketListingRecord.created_at < day_end,
                ).limit(1)
            ) is not None,
        }

    def club_tasks(self, platform_id: str, now: datetime) -> list[dict]:
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now)
                today = now.astimezone(BEIJING).date()
                eligibility = self._club_task_eligibility(session, player, now)
                claimed: set[str] = set()
                if player.user_id:
                    claimed = set(session.scalars(select(ClubTaskClaimRecord.task_key).where(
                        ClubTaskClaimRecord.user_id == player.user_id,
                        or_(
                            ClubTaskClaimRecord.task_key == "employment",
                            ClubTaskClaimRecord.claim_date == today,
                        ),
                    )))
                return [
                    {
                        "key": key,
                        "reward": reward,
                        "eligible": eligibility[key],
                        "claimed": key in claimed,
                        "hidden": key == "activity",
                        "cadence": "daily" if key in DAILY_TASKS else "once",
                    }
                    for key, reward in TASK_REWARDS.items()
                ]

    def claim_club_task(self, platform_id: str, task_key: str, now: datetime) -> dict:
        if task_key not in TASK_REWARDS:
            raise ValueError("任务不存在")
        with self.transaction():
            with self._session() as session:
                player = self._club_player(session, platform_id, now, lock=True)
                if player.user_id is None or is_bot_platform_id(platform_id):
                    raise ValueError("领取任务奖励需要先入职")
                user = session.get(UserRecord, player.user_id, with_for_update=True)
                today = now.astimezone(BEIJING).date()
                claim_date = today if task_key in DAILY_TASKS else None
                existing = session.scalar(
                    select(ClubTaskClaimRecord).where(
                        ClubTaskClaimRecord.user_id == user.id,
                        ClubTaskClaimRecord.task_key == task_key,
                        *(
                            [ClubTaskClaimRecord.claim_date == claim_date]
                            if task_key in DAILY_TASKS else []
                        ),
                    )
                )
                if existing is not None:
                    raise ValueError("今日奖励已经领取" if task_key in DAILY_TASKS else "奖励已经领取")
                if not self._club_task_eligibility(session, player, now)[task_key]:
                    raise ValueError("任务尚未完成")
                reward = TASK_REWARDS[task_key]
                self._apply_balance_change(
                    user,
                    reward,
                    "club_task_reward",
                    now,
                    memo=f"Club {'每日' if task_key in DAILY_TASKS else '一次性'}任务：{task_key}",
                )
                session.add(ClubTaskClaimRecord(
                    user_id=user.id,
                    task_key=task_key,
                    claim_date=claim_date,
                    reward=reward,
                    claimed_at=now,
                ))
                session.flush()
                return {"task_key": task_key, "reward": reward, "balance": user.balance}
