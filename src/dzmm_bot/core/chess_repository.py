from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import randbelow
from uuid import UUID

from sqlalchemy import delete, select, update

from .chess_rules import (
    ChessMove, ChessPosition, ChessViolation, IllegalChessMove, adjudicate_repetition,
    basic_outcome, checked_king, initial_position, play_move,
)
from .schema import ClubPlayerRecord, ChessGameRecord, ChessMessageRecord, ChessMoveRecord, GroupChatRecord, InboundRecord, OutboundRecord, UserRecord


COIN_STAKES = {5, 10, 20}


@dataclass(frozen=True)
class ChessGameView:
    id: UUID
    group_chat_id: UUID | None
    inbound_message_id: UUID | None
    creator_platform_id: str
    opponent_platform_id: str | None
    red_platform_id: str | None
    black_platform_id: str | None
    code: str
    room_type: str
    stake: int
    settlement: dict | None
    status: str
    created_at: datetime
    claim_deadline: datetime
    position: dict | None
    red_remaining_ms: int
    black_remaining_ms: int
    turn_started_at: datetime | None
    version: int
    result: str | None
    pending_offer: str | None
    offer_platform_id: str | None
    finished_at: datetime | None
    events: list
    rematch_ready: tuple[str, ...]
    check_square: list[int] | None


@dataclass(frozen=True)
class ChessClaimResult:
    status: str
    game: ChessGameView | None = None


class ChessRateLimitError(ValueError):
    pass


class ChessRepositoryMixin:
    @staticmethod
    def _chess_account(session, player, *, lock=False):
        if player.user_id is None:
            raise ValueError("摸鱼币场仅限已入职员工")
        query = select(UserRecord).where(UserRecord.id == player.user_id)
        if lock:
            query = query.with_for_update()
        account = session.scalar(query)
        if account is None:
            raise ValueError("摸鱼币场仅限已入职员工")
        return account

    def chess_inbound_id(self, group_chat_id: UUID, platform_message_id: str) -> UUID | None:
        with self.transaction(), self._session() as session:
            return session.scalar(select(InboundRecord.id).where(
                InboundRecord.group_chat_id == group_chat_id,
                InboundRecord.platform_message_id == platform_message_id,
                InboundRecord.source_type == "group",
            ))

    @staticmethod
    def _position_data(position: ChessPosition) -> dict:
        return {"board": list(position.board), "turn": position.turn}

    @staticmethod
    def _position(value: dict) -> ChessPosition:
        return ChessPosition(tuple(value["board"]), value["turn"])

    def _chess_view(self, session, row: ChessGameRecord) -> ChessGameView:
        def pid(user_id):
            player = session.get(ClubPlayerRecord, user_id) if user_id else None
            return player.platform_id if player else None

        return ChessGameView(
            id=row.id, group_chat_id=row.group_chat_id, inbound_message_id=row.inbound_message_id,
            creator_platform_id=pid(row.creator_user_id), opponent_platform_id=pid(row.opponent_user_id),
            red_platform_id=pid(row.red_user_id), black_platform_id=pid(row.black_user_id),
            code=row.code, room_type=row.room_type, stake=row.stake, settlement=row.settlement,
            status=row.status, created_at=row.created_at, claim_deadline=row.claim_deadline,
            position=row.position, red_remaining_ms=row.red_remaining_ms,
            black_remaining_ms=row.black_remaining_ms, turn_started_at=row.turn_started_at,
            version=row.version, result=row.result, pending_offer=row.pending_offer,
            offer_platform_id=pid(row.offer_user_id), finished_at=row.finished_at,
            events=row.events or [],
            rematch_ready=self._chess_rematch_ready(row),
            check_square=checked_king(self._position(row.position)) if row.position else None,
        )

    @staticmethod
    def _chess_rematch_ready(row: ChessGameRecord) -> tuple[str, ...]:
        ready = set()
        for event in row.events or []:
            if event.get("kind") == "finish":
                ready.clear()
            elif event.get("kind") == "rematch_ready":
                ready.add(event.get("color"))
            elif event.get("kind") == "rematch_unready":
                ready.discard(event.get("color"))
        return tuple(color for color in ("red", "black") if color in ready)

    @staticmethod
    def _chess_event(row, kind, now, **data):
        events = row.events or []
        row.events = events + [{"seq": len(events) + 1, "kind": kind, "at": now.isoformat(), **data}]

    def _seed_chess_events(self, session, row):
        if row.events:
            return
        records = session.scalars(select(ChessMoveRecord).where(ChessMoveRecord.game_id == row.id).order_by(ChessMoveRecord.ply)).all()
        for record in records:
            before = self._position(record.position_before)
            after = play_move(before, ChessMove(record.from_x, record.from_y, record.to_x, record.to_y))
            self._chess_event(row, "move", record.created_at, move_id=str(record.id), ply=record.ply,
                              color=before.turn, from_xy=[record.from_x, record.from_y], to_xy=[record.to_x, record.to_y],
                              piece=before.board[record.from_y][record.from_x], captured=before.board[record.to_y][record.to_x],
                              check=checked_king(after) is not None)

    def create_chess_game(
        self, creator_platform_id: str, group_chat_id: UUID | None = None,
        inbound_id: UUID | None = None, now: datetime | None = None, *,
        room_type: str = "casual", stake: int = 0,
    ) -> ChessGameView:
        if room_type not in {"casual", "coin"}:
            raise ValueError("房间类型无效")
        if room_type == "casual":
            stake = 0
        elif stake not in COIN_STAKES:
            raise ValueError("摸鱼币场仅支持 5、10、20 币")
        with self.transaction(), self._session() as session:
            creator = self._club_player(session, creator_platform_id, now, lock=True)
            self._ensure_club_player_available(session, creator.id, now)
            if group_chat_id is not None:
                group = session.get(GroupChatRecord, group_chat_id)
                inbound = session.get(InboundRecord, inbound_id)
                if group is None or not group.listening_enabled or inbound is None or inbound.group_chat_id != group_chat_id or inbound.sender_platform_id != creator_platform_id:
                    raise ValueError("群聊或入站消息不可用")
            account = None
            if room_type == "coin":
                account = self._chess_account(session, creator, lock=True)
                if account.balance < stake:
                    raise ValueError(f"余额不足，需要{stake}摸鱼币")
            row = ChessGameRecord(
                group_chat_id=group_chat_id, inbound_message_id=inbound_id,
                creator_user_id=creator.id, code=f"{randbelow(10000):04d}",
                room_type=room_type, stake=stake,
                escrowed=[room_type == "coin", False], settled=False,
                status="waiting", created_at=now, claim_deadline=now + timedelta(minutes=10),
                red_remaining_ms=900000, black_remaining_ms=900000, version=0,
            )
            session.add(row)
            session.flush()
            if account is not None:
                self._apply_balance_change(account, -stake, "chess_buy_in", now,
                                           memo=f"象棋房间 {row.id} 入场托管")
            return self._chess_view(session, row)

    def get_chess_game(self, game_id: UUID) -> ChessGameView:
        with self._session() as session:
            row = session.get(ChessGameRecord, game_id)
            if row is None:
                raise ValueError("棋局不存在")
            return self._chess_view(session, row)

    def list_chess_rooms(self, now: datetime) -> list[dict]:
        with self._session() as session:
            rows = session.execute(
                select(ChessGameRecord, ClubPlayerRecord.display_name)
                .join(ClubPlayerRecord, ClubPlayerRecord.id == ChessGameRecord.creator_user_id)
                .where(
                    (ChessGameRecord.status == "playing")
                    | ((ChessGameRecord.status == "waiting") & (ChessGameRecord.claim_deadline > now)),
                    (ChessGameRecord.inbound_message_id.is_(None))
                    | select(OutboundRecord.id).where(
                            OutboundRecord.inbound_message_id == ChessGameRecord.inbound_message_id,
                            OutboundRecord.content_type == "text",
                            OutboundRecord.status == "sent",
                        ).exists(),
                )
                .order_by(ChessGameRecord.created_at.desc())
            ).all()
            return [{"id": str(row.id), "creator_name": name, "status": row.status,
                     "room_type": row.room_type, "stake": row.stake} for row, name in rows]

    def claim_chess_seat(
        self, game_id: UUID, platform_id: str, code: str | None, now: datetime
    ) -> ChessClaimResult:
        with self.transaction(), self._session() as session:
            row = session.get(ChessGameRecord, game_id)
            if row is None:
                return ChessClaimResult("not_found")
            user = self._club_player(session, platform_id, now, lock=True)
            if row.status != "waiting":
                return ChessClaimResult("occupied", self._chess_view(session, row))
            if user.id == row.creator_user_id:
                return ChessClaimResult("same_player")
            if now >= row.claim_deadline:
                return ChessClaimResult("expired")
            if row.inbound_message_id is not None and code != row.code:
                return ChessClaimResult("invalid_code")
            if row.inbound_message_id is not None:
                sent = session.scalar(
                    select(OutboundRecord.id).where(
                        OutboundRecord.inbound_message_id == row.inbound_message_id,
                        OutboundRecord.group_chat_id == row.group_chat_id,
                        OutboundRecord.status == "sent",
                        OutboundRecord.content_type == "text",
                    ).limit(1)
                )
                if sent is None:
                    return ChessClaimResult("not_announced")
            self._ensure_club_player_available(
                session, user.id, now, exclude=("chess", row.id),
            )
            if row.room_type == "coin":
                account = self._chess_account(session, user, lock=True)
                if account.balance < row.stake:
                    return ChessClaimResult("insufficient_balance")
                self._apply_balance_change(account, -row.stake, "chess_buy_in", now,
                                           memo=f"象棋房间 {row.id} 入场托管")
            creator_red = randbelow(2) == 0
            values = {
                "opponent_user_id": user.id,
                "red_user_id": row.creator_user_id if creator_red else user.id,
                "black_user_id": user.id if creator_red else row.creator_user_id,
                "status": "playing", "turn_started_at": now, "version": 1,
                "position": self._position_data(initial_position()),
                "escrowed": [row.room_type == "coin", row.room_type == "coin"],
                "code": "",  # Used code is never usable again.
            }
            result = session.execute(
                update(ChessGameRecord)
                .where(ChessGameRecord.id == game_id, ChessGameRecord.status == "waiting")
                .values(**values)
            )
            session.flush()
            session.expire_all()
            row = session.get(ChessGameRecord, game_id)
            return ChessClaimResult("claimed" if result.rowcount == 1 else "occupied", self._chess_view(session, row))

    @staticmethod
    def _chess_notice(session, row: ChessGameRecord, text: str) -> None:
        if row.group_chat_id is None:
            return
        group = session.get(GroupChatRecord, row.group_chat_id)
        if group is None or group.chatroom_id is None:
            return
        session.add(OutboundRecord(
            group_chat_id=row.group_chat_id, destination_chatroom_id=group.chatroom_id,
            delivery_key=group.chatroom_id, delivery_kind="group", text=text,
        ))

    def _refund_chess_room(self, session, row, now, reason):
        if row.room_type != "coin":
            return
        escrowed = list(row.escrowed or [False, False])
        player_ids = [row.creator_user_id, row.opponent_user_id]
        for index, held in enumerate(escrowed):
            if not held or player_ids[index] is None:
                continue
            player = session.get(ClubPlayerRecord, player_ids[index])
            account = session.get(UserRecord, player.user_id, with_for_update=True) if player and player.user_id else None
            if account is not None:
                self._apply_balance_change(
                    account, row.stake, "chess_refund", now,
                    memo=f"象棋房间 {row.id}：{reason}",
                )
            escrowed[index] = False
        row.escrowed = escrowed

    def _settle_chess_room(self, session, row, result, now):
        if row.settled:
            return
        winner, _ = result.split(":", 1)
        payouts = {"red": 0, "black": 0}
        outcomes = {"red": "draw", "black": "draw"}
        if row.room_type == "coin":
            if not all(row.escrowed):
                raise RuntimeError("象棋奖池托管不完整")
            if winner == "draw":
                self._refund_chess_room(session, row, now, "和棋退还")
                payouts = {"red": row.stake, "black": row.stake}
            else:
                player_id = row.red_user_id if winner == "red" else row.black_user_id
                player = session.get(ClubPlayerRecord, player_id)
                account = session.get(UserRecord, player.user_id, with_for_update=True) if player and player.user_id else None
                if account is None:
                    raise RuntimeError("象棋结算玩家不存在")
                payout = row.stake * 2
                payouts[winner] = payout
                self._apply_balance_change(
                    account, payout, "chess_settlement", now,
                    memo=f"象棋房间 {row.id} 胜方结算",
                )
                row.escrowed = [False, False]
        if winner != "draw":
            loser = "black" if winner == "red" else "red"
            outcomes = {winner: "win", loser: "loss"}
        row.settled = True
        row.settlement = {"winner": winner, "payouts": payouts, "outcomes": outcomes}

    def _finish_chess(self, session, row: ChessGameRecord, result: str, now: datetime) -> None:
        if row.status != "playing":
            return
        self._seed_chess_events(session, row)
        self._chess_event(row, "finish", now, result=result)
        row.status = "finished"
        row.result = result
        row.finished_at = now
        row.turn_started_at = None
        row.pending_offer = None
        row.offer_user_id = None
        row.version += 1
        self._settle_chess_room(session, row, result, now)
        names = {
            "red": session.get(ClubPlayerRecord, row.red_user_id).display_name,
            "black": session.get(ClubPlayerRecord, row.black_user_id).display_name,
        }
        winner, reason = result.split(":", 1)
        sides = {"red": "红方", "black": "黑方"}
        if winner == "draw":
            text = f"♟ 象棋对局结束 · 双方和棋\n红方：{names['red']}\n黑方：{names['black']}\n原因：双方同意和棋"
        else:
            loser = "black" if winner == "red" else "red"
            reasons = {
                "checkmate": f"{sides[winner]}绝杀，{sides[loser]}被将死",
                "stalemate": f"{sides[loser]}困毙，无合法着法",
                "step_timeout": f"{sides[loser]}单步超时",
                "total_timeout": f"{sides[loser]}总用时耗尽",
                "resign": f"{sides[loser]}认输",
                "long_check": f"{sides[loser]}长将判负",
                "long_chase": f"{sides[loser]}长捉判负",
            }
            text = f"♟ 象棋对局结束\n🏆 胜利：{names[winner]}（{sides[winner]}）\n落败：{names[loser]}（{sides[loser]}）\n原因：{reasons.get(reason, '对局结束')}"
        self._chess_notice(session, row, text)

    @staticmethod
    def _elapsed_ms(row: ChessGameRecord, now: datetime) -> int:
        return max(0, int((now - row.turn_started_at).total_seconds() * 1000))

    def _timeout_chess(self, session, row: ChessGameRecord, now: datetime) -> bool:
        if row.status != "playing" or row.turn_started_at is None:
            return False
        color = row.position["turn"]
        remaining = row.red_remaining_ms if color == "red" else row.black_remaining_ms
        elapsed = self._elapsed_ms(row, now)
        if elapsed < min(remaining, 60000):
            return False
        winner = "black" if color == "red" else "red"
        reason = "total_timeout" if remaining <= 60000 else "step_timeout"
        self._finish_chess(session, row, f"{winner}:{reason}", now)
        return True

    def play_chess(
        self, game_id: UUID, platform_id: str, from_xy: tuple[int, int],
        to_xy: tuple[int, int], expected_version: int, now: datetime,
    ) -> ChessGameView:
        with self.transaction(), self._session() as session:
            row = session.scalar(select(ChessGameRecord).where(ChessGameRecord.id == game_id).with_for_update())
            if row is None or row.status != "playing":
                raise ValueError("棋局未在进行")
            if self._timeout_chess(session, row, now):
                return self._chess_view(session, row)
            if row.version != expected_version:
                raise ValueError("棋局版本已变化")
            position = self._position(row.position)
            user = self._club_player(session, platform_id, now)
            current_user_id = row.red_user_id if position.turn == "red" else row.black_user_id
            if user is None or user.id != current_user_id:
                raise ValueError("现在不是你的回合")
            move = ChessMove(*from_xy, *to_xy)
            next_position = play_move(position, move)
            self._seed_chess_events(session, row)
            records = session.scalars(select(ChessMoveRecord).where(ChessMoveRecord.game_id == game_id).order_by(ChessMoveRecord.ply)).all()
            history = tuple(self._position(record.position_before) for record in records) + (position, next_position)
            moves = tuple(ChessMove(record.from_x, record.from_y, record.to_x, record.to_y) for record in records) + (move,)
            violation = adjudicate_repetition(history, moves)
            long_chase_loss = (
                isinstance(violation, ChessViolation)
                and violation.reason == "long_chase"
                and violation.side == position.turn
                and history.count(next_position) >= 4
            )
            elapsed = self._elapsed_ms(row, now)
            if position.turn == "red":
                row.red_remaining_ms -= elapsed
            else:
                row.black_remaining_ms -= elapsed
            row.position = self._position_data(next_position)
            row.turn_started_at = now
            row.version += 1
            row.pending_offer = None
            row.offer_user_id = None
            move_record = ChessMoveRecord(
                game_id=game_id, ply=len(records) + 1,
                from_x=move.from_x, from_y=move.from_y, to_x=move.to_x, to_y=move.to_y,
                position_before=self._position_data(position), created_at=now,
            )
            session.add(move_record)
            session.flush()
            self._chess_event(row, "move", now, move_id=str(move_record.id), ply=len(records) + 1,
                              color=position.turn, from_xy=list(from_xy), to_xy=list(to_xy),
                              piece=position.board[move.from_y][move.from_x], captured=position.board[move.to_y][move.to_x],
                              check=checked_king(next_position) is not None)
            outcome = basic_outcome(next_position)
            if isinstance(violation, ChessViolation) and violation.reason == "long_check":
                winner = "black" if violation.side == "red" else "red"
                self._finish_chess(session, row, f"{winner}:long_check", now)
            elif long_chase_loss:
                winner = "black" if position.turn == "red" else "red"
                self._finish_chess(session, row, f"{winner}:long_chase", now)
            elif outcome is not None:
                self._finish_chess(session, row, f"{outcome.winner}:{outcome.reason}", now)
            return self._chess_view(session, row)

    def chess_action(self, game_id: UUID, platform_id: str, action: str, now: datetime, expected_version: int) -> ChessGameView:
        valid = {"offer_undo", "accept_undo", "decline_undo", "offer_draw", "accept_draw", "decline_draw", "resign", "ready", "unready", "start"}
        if action not in valid:
            raise ValueError("未知的象棋操作")
        with self.transaction(), self._session() as session:
            row = session.scalar(select(ChessGameRecord).where(ChessGameRecord.id == game_id).with_for_update())
            if row is None:
                raise ValueError("棋局不存在")
            if row.version != expected_version:
                raise ValueError("棋局版本已变化")
            user = self._club_player(session, platform_id, now)
            if user is None or user.id not in {row.red_user_id, row.black_user_id}:
                raise ValueError("只有棋手能执行此操作")
            color = "red" if user.id == row.red_user_id else "black"
            if row.status == "finished":
                ready = set(self._chess_rematch_ready(row))
                if action in {"ready", "unready"}:
                    self._chess_event(row, f"rematch_{action}", now, color=color)
                    row.version += 1
                    return self._chess_view(session, row)
                if action != "start" or user.id != row.creator_user_id:
                    raise ValueError("只有房主可以开始下一局")
                if ready != {"red", "black"}:
                    raise ValueError("请等待双方准备")
                if row.room_type == "coin":
                    players = [session.get(ClubPlayerRecord, row.red_user_id), session.get(ClubPlayerRecord, row.black_user_id)]
                    accounts = [self._chess_account(session, player, lock=True) for player in players]
                    for player, account in zip(players, accounts):
                        if account.balance < row.stake:
                            raise ValueError(f"{player.display_name}余额不足，无法续局")
                    for account in accounts:
                        self._apply_balance_change(account, -row.stake, "chess_buy_in", now,
                                                   memo=f"象棋房间 {row.id} 续局托管")
                session.execute(delete(ChessMoveRecord).where(ChessMoveRecord.game_id == row.id))
                row.status = "playing"
                row.position = self._position_data(initial_position())
                row.red_remaining_ms = row.black_remaining_ms = 900000
                row.turn_started_at = now
                row.version += 1
                row.result = None
                row.finished_at = None
                row.pending_offer = None
                row.offer_user_id = None
                row.events = []
                row.escrowed = [row.room_type == "coin"] * 2
                row.settled = False
                row.settlement = None
                return self._chess_view(session, row)
            if row.status != "playing":
                raise ValueError("棋局未在进行")
            if self._timeout_chess(session, row, now):
                return self._chess_view(session, row)
            self._seed_chess_events(session, row)
            if action == "resign":
                self._chess_event(row, action, now, color=color)
                self._finish_chess(session, row, f"{'black' if color == 'red' else 'red'}:resign", now)
            elif action.startswith("offer_"):
                if row.pending_offer is not None:
                    raise ValueError("已有待处理请求")
                if action == "offer_undo" and session.scalar(select(ChessMoveRecord.id).where(ChessMoveRecord.game_id == game_id).limit(1)) is None:
                    raise ValueError("还没有可悔的棋")
                row.pending_offer = action.removeprefix("offer_")
                row.offer_user_id = user.id
                row.version += 1
                self._chess_event(row, action, now, color=color)
            else:
                kind = action.split("_", 1)[1]
                if row.pending_offer != kind or row.offer_user_id == user.id:
                    raise ValueError("没有对手的待处理请求")
                if action.startswith("decline_"):
                    row.pending_offer = None
                    row.offer_user_id = None
                    row.version += 1
                    self._chess_event(row, action, now, color=color)
                elif kind == "draw":
                    self._chess_event(row, action, now, color=color)
                    self._finish_chess(session, row, "draw:agreement", now)
                else:
                    last = session.scalar(select(ChessMoveRecord).where(ChessMoveRecord.game_id == game_id).order_by(ChessMoveRecord.ply.desc()).limit(1))
                    if last is None:
                        raise ValueError("还没有可悔的棋")
                    elapsed = self._elapsed_ms(row, now)
                    if row.position["turn"] == "red":
                        row.red_remaining_ms -= elapsed
                    else:
                        row.black_remaining_ms -= elapsed
                    row.position = last.position_before
                    row.turn_started_at = now
                    row.pending_offer = None
                    row.offer_user_id = None
                    row.version += 1
                    undone_seq = next(event["seq"] for event in row.events if event.get("move_id") == str(last.id))
                    self._chess_event(row, action, now, color=color, undone_seq=undone_seq)
                    session.delete(last)
            return self._chess_view(session, row)

    def _advance_chess_row(self, session, row: ChessGameRecord, now: datetime) -> bool:
        if row.status == "waiting" and now >= row.claim_deadline:
            self._refund_chess_room(session, row, now, "等待超时")
            row.status = "cancelled"
            row.version += 1
            sent = session.scalar(select(OutboundRecord.id).where(
                OutboundRecord.inbound_message_id == row.inbound_message_id,
                OutboundRecord.status == "sent",
            ).limit(1))
            if sent is not None:
                self._chess_notice(session, row, f"象棋对局 {row.id} 等候超时，已取消。")
            return True
        return self._timeout_chess(session, row, now)

    def settle_chess_deadline(self, game_id: UUID, now: datetime) -> None:
        with self.transaction(), self._session() as session:
            row = session.scalar(select(ChessGameRecord).where(ChessGameRecord.id == game_id).with_for_update())
            if row is not None:
                self._advance_chess_row(session, row, now)

    def advance_chess_deadlines(self, now: datetime) -> int:
        with self.transaction(), self._session() as session:
            rows = session.scalars(
                select(ChessGameRecord).where(ChessGameRecord.status.in_(("waiting", "playing"))).with_for_update()
            ).all()
            return sum(self._advance_chess_row(session, row, now) for row in rows)

    def chess_messages(self, game_id: UUID) -> list[dict]:
        with self._session() as session:
            row = session.get(ChessGameRecord, game_id)
            if row is None:
                return []
            records = session.scalars(
                select(ChessMessageRecord)
                .where(ChessMessageRecord.game_id == game_id)
                .order_by(ChessMessageRecord.created_at, ChessMessageRecord.id)
            ).all()
            return [
                {"id": str(item.id), "sender": session.get(ClubPlayerRecord, item.user_id).display_name,
                 "text": item.content, "created_at": item.created_at.isoformat()}
                for item in records
            ]

    def chess_moves(self, game_id: UUID) -> list[dict]:
        with self._session() as session:
            records = session.scalars(
                select(ChessMoveRecord)
                .where(ChessMoveRecord.game_id == game_id)
                .order_by(ChessMoveRecord.ply)
            ).all()
            return [
                {"ply": item.ply, "from_xy": [item.from_x, item.from_y],
                 "to_xy": [item.to_x, item.to_y]}
                for item in records
            ]

    def chess_chat(self, game_id: UUID, platform_id: str, text: str, now: datetime) -> dict:
        content = text.strip()
        if not content or len(content) > 300 or any(ord(char) < 32 and char not in "\n\t" for char in content):
            raise ValueError("聊天内容须为 1～300 字纯文字")
        with self._session() as session:
            game = session.scalar(select(ChessGameRecord).where(ChessGameRecord.id == game_id).with_for_update())
            user = self._club_player(session, platform_id, now)
            if game is None or game.status not in ("waiting", "playing", "finished"):
                raise ValueError("当前不可发送聊天")
            last = session.scalar(
                select(ChessMessageRecord.created_at)
                .where(ChessMessageRecord.game_id == game_id, ChessMessageRecord.user_id == user.id)
                .order_by(ChessMessageRecord.created_at.desc()).limit(1)
            )
            if last is not None and (now - last).total_seconds() < 2:
                raise ChessRateLimitError("请稍后再发")
            message = ChessMessageRecord(game_id=game_id, user_id=user.id, content=content, created_at=now)
            session.add(message)
            session.flush()
            return {"id": str(message.id), "sender": user.display_name, "text": content, "created_at": now.isoformat()}
