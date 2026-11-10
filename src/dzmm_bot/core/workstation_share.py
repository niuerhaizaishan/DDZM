import json
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import func, select

from .schema import GroupChatRecord, InboundRecord, OutboundRecord, UserRecord


def share_record_id(user_id, request_id):
    return uuid5(NAMESPACE_URL, f"ddzm:workstation-share:{user_id}:{request_id}")


def available_share_groups(repository, platform_id, now):
    with repository._session() as session:
        rows = session.execute(
            select(GroupChatRecord.id, GroupChatRecord.name)
            .join(InboundRecord, InboundRecord.group_chat_id == GroupChatRecord.id)
            .where(
                InboundRecord.sender_platform_id == platform_id,
                InboundRecord.source_type == "group",
                func.trim(InboundRecord.content) == "/我的工位",
                InboundRecord.received_at >= now - timedelta(hours=24),
                InboundRecord.received_at <= now,
                GroupChatRecord.deleted_at.is_(None),
                GroupChatRecord.listening_enabled.is_(True),
                GroupChatRecord.chatroom_id.is_not(None),
            ).order_by(InboundRecord.received_at.desc(), InboundRecord.id.desc())
        ).all()
        unique = {}
        for identifier, name in rows:
            unique.setdefault(str(identifier), {"id": str(identifier), "name": name})
        return list(unique.values())


def share_status(repository, user_id, request_id):
    with repository._session() as session:
        record = session.get(OutboundRecord, share_record_id(user_id, request_id))
        if record is None or record.content_type != "workstation":
            raise HTTPException(404, "没有找到这次发送记录。")
        return {"request_id": str(request_id), "status": record.status}


def enqueue_workstation_share(repository, user_id, group_id, request_id, now):
    with repository.transaction():
        with repository._session() as session:
            user = session.get(UserRecord, user_id, with_for_update=True)
            if user is None:
                raise HTTPException(404, "尚未找到你的员工档案。")
            groups = available_share_groups(repository, user.platform_id, now)
            if str(group_id) not in {group["id"] for group in groups}:
                raise HTTPException(403, "请先在目标群发送 /我的工位，再刷新本页；发图入口有效期为24小时。")
            identifier = share_record_id(user.id, request_id)
            existing = session.get(OutboundRecord, identifier)
            if existing is not None:
                if existing.group_chat_id != group_id:
                    raise HTTPException(409, "这次发送已选择其他群，请刷新后重试。")
                return share_status(repository, user.id, request_id)
            prefix = json.dumps({"owner_id": str(user.id)})[:-1] + ","
            recent = session.scalar(select(OutboundRecord.id).where(
                OutboundRecord.content_type == "workstation",
                OutboundRecord.text.startswith(prefix),
                OutboundRecord.created_at > now - timedelta(seconds=60),
            ).limit(1))
            if recent is not None:
                raise HTTPException(429, "发送过于频繁，请在一分钟后再试。")
            group = session.get(GroupChatRecord, group_id, with_for_update=True)
            if group.deleted_at is not None or not group.listening_enabled or not group.chatroom_id:
                raise HTTPException(403, "目标群暂不可用，请刷新后重试。")
            payload = {"owner_id": str(user.id), **repository.get_workstation(user.id)}
            record = repository.enqueue_system_outbound(
                json.dumps(payload, ensure_ascii=False), group_chat_id=group.id,
                destination_chatroom_id=group.chatroom_id,
                content_type="workstation",
            )
            record.id = identifier
            record.created_at = now
            record.updated_at = now
            session.flush()
            return {"request_id": str(request_id), "status": record.status}
