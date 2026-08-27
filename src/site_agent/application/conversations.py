"""Durable conversation lifecycle service."""

from __future__ import annotations

from typing import Any


class ConversationServiceError(ValueError):
    def __init__(self, message: str, conversation_id: int, job_ids: list[int] | None = None) -> None:
        self.conversation_id = conversation_id
        self.job_ids = list(job_ids or [])
        super().__init__(message)


class ConversationNotFound(ConversationServiceError):
    def __init__(self, conversation_id: int) -> None:
        super().__init__(f"no such conversation: {conversation_id}", conversation_id)


class ConversationBusy(ConversationServiceError):
    def __init__(self, conversation_id: int, job_ids: list[int]) -> None:
        super().__init__("conversation has queued or running work", conversation_id, job_ids)


class ConversationService:
    def __init__(self, memory):
        self.memory = memory

    def create(self, title: str = "New conversation") -> int:
        return self.memory.create_conversation(title)

    def list(self, *, include_archived: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        return self.memory.list_conversations(limit=limit, include_archived=include_archived)

    def get(self, conversation_id: int) -> dict[str, Any]:
        conversation = self.memory.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        deleted = bool(conversation.get("deleted_ts"))
        return {
            **conversation,
            "deleted": deleted,
            "messages": [] if deleted else self.memory.get_messages(conversation_id),
            "jobs": self.memory.list_chat_jobs(conversation_id),
        }

    def archive(self, conversation_id: int) -> dict[str, Any]:
        conversation = self._require_mutable(conversation_id)
        job_ids = self._active_job_ids(conversation_id)
        if job_ids:
            raise ConversationBusy(conversation_id, job_ids)
        if not self.memory.archive_conversation(conversation_id):
            raise ConversationNotFound(conversation_id)
        updated = self.memory.get_conversation(conversation_id) or conversation
        return {**updated, "archived": True, "conversation_id": conversation_id, "job_ids": []}

    def restore(self, conversation_id: int) -> dict[str, Any]:
        conversation = self.memory.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        if conversation.get("deleted_ts"):
            raise ConversationServiceError("deleted conversations cannot be restored", conversation_id)
        if not conversation.get("archived_ts"):
            return {**conversation, "archived": False, "conversation_id": conversation_id}
        if not self.memory.restore_conversation(conversation_id):
            raise ConversationNotFound(conversation_id)
        return {**conversation, "archived_ts": None, "archived": False, "conversation_id": conversation_id}

    def delete(self, conversation_id: int) -> dict[str, Any]:
        self._require_mutable(conversation_id)
        job_ids = self._active_job_ids(conversation_id)
        if job_ids:
            raise ConversationBusy(conversation_id, job_ids)
        result = self.memory.delete_conversation_content(conversation_id)
        if result is None:
            raise ConversationNotFound(conversation_id)
        if result.get("blocked_job_ids"):
            raise ConversationBusy(conversation_id, result["blocked_job_ids"])
        return result

    def archive_all(self, keep_id: int | None = None) -> dict[str, Any]:
        archived: list[int] = []
        blocked: dict[int, list[int]] = {}
        for conversation in self.list(include_archived=False, limit=500):
            conversation_id = conversation["id"]
            if keep_id is not None and conversation_id == keep_id:
                continue
            job_ids = self._active_job_ids(conversation_id)
            if job_ids:
                blocked[conversation_id] = job_ids
                continue
            if self.memory.archive_conversation(conversation_id):
                archived.append(conversation_id)
        return {
            "archived_ids": archived,
            "archived": len(archived),
            "blocked": blocked,
            "kept_conversation_id": keep_id,
        }

    def _require_mutable(self, conversation_id: int) -> dict[str, Any]:
        conversation = self.memory.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound(conversation_id)
        if conversation.get("deleted_ts"):
            raise ConversationServiceError("conversation has already been deleted", conversation_id)
        return conversation

    def _active_job_ids(self, conversation_id: int) -> list[int]:
        return [job["id"] for job in self.memory.list_active_chat_jobs(conversation_id=conversation_id, limit=100)]
