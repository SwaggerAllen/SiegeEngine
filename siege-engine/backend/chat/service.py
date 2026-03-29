"""Chat service managing Claude CLI subprocess sessions per project.

Architecture:
- ChatSession owns the CLI subprocess lifecycle and runs generation as
  an asyncio background task, decoupled from any WebSocket connection.
- Each session has an event bus (asyncio.Queue per subscriber) so multiple
  WS connections can observe the same generation.
- The WS handler is a stateless subscriber: connect → subscribe → relay events.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.cli.manager import CLIManager
from backend.database import SessionLocal
from backend.models import Artifact, PipelineSnapshot
from backend.models.chat import ChatMessage

logger = logging.getLogger(__name__)

_MAX_REINJECT_CHARS = 50_000


# ── Event types emitted by the session ──────────────────────────────────────


class EventType(str, Enum):
    HISTORY = "history"
    PINS_UPDATED = "pins_updated"
    RESPONSE_START = "response_start"
    RESPONSE_CHUNK = "response_chunk"
    RESPONSE_END = "response_end"
    RESPONSE_GENERATING = "response_generating"
    GENERATION_COMPLETE = "generation_complete"
    SESSION_RESET = "session_reset"
    ERROR = "error"


@dataclass
class ChatEvent:
    type: EventType
    data: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"type": self.type.value, **self.data}


# ── ChatSession: owns CLI lifecycle, runs generation as background task ─────


class ChatSession:
    """A single chat session backed by Claude CLI."""

    CHAT_TOOLS = "Bash,Read,Glob,Grep,WebFetch,WebSearch,Agent,TodoWrite"
    CHAT_SYSTEM_PROMPT = (
        "You have read-only access to this repository. "
        "Do NOT use Bash to create, modify, or delete any files or directories "
        "(no rm, mv, cp, touch, mkdir, sed -i, tee, redirects like > or >>, etc.). "
        "Only use Bash for read-only commands such as git log, git diff, ls, find, "
        "grep, cat, head, tail, wc, etc."
    )

    def __init__(self, session_id: str, working_dir: str, project_id: str):
        self.session_id = session_id
        self.working_dir = working_dir
        self.project_id = project_id
        self.message_count = 0
        self.pinned_artifact_ids: list[str] = []
        self._needs_reinject = False
        self.is_generating = False
        self._generation_task: asyncio.Task | None = None

        # Subscriber queues: each connected WS gets its own queue
        self._subscribers: dict[str, asyncio.Queue[ChatEvent]] = {}

    # ── Subscriber management ───────────────────────────────────────────

    def subscribe(self) -> tuple[str, asyncio.Queue[ChatEvent]]:
        """Register a new subscriber. Returns (subscriber_id, queue)."""
        sub_id = str(uuid.uuid4())[:8]
        queue: asyncio.Queue[ChatEvent] = asyncio.Queue()
        self._subscribers[sub_id] = queue
        logger.debug("Subscriber %s added to session %s (%d total)",
                      sub_id, self.session_id, len(self._subscribers))
        return sub_id, queue

    def unsubscribe(self, sub_id: str):
        """Remove a subscriber."""
        self._subscribers.pop(sub_id, None)
        logger.debug("Subscriber %s removed from session %s (%d remaining)",
                      sub_id, self.session_id, len(self._subscribers))

    def _broadcast(self, event: ChatEvent):
        """Push event to all subscriber queues (non-blocking)."""
        for queue in self._subscribers.values():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full, dropping event %s", event.type)

    # ── Context building ────────────────────────────────────────────────

    def _build_system_prompt(self, db: Session) -> str:
        parts = [self.CHAT_SYSTEM_PROMPT]

        snapshot = (
            db.query(PipelineSnapshot)
            .filter_by(project_id=self.project_id)
            .first()
        )
        if snapshot and snapshot.stage_statuses:
            lines = ["", "Pipeline Status:"]
            for stage_key, status in snapshot.stage_statuses.items():
                version = (snapshot.artifact_versions or {}).get(stage_key, "")
                ver_str = f" (v{version})" if version else ""
                lines.append(f"  - {stage_key}: {status}{ver_str}")
            if snapshot.is_running:
                lines.append(f"  (Currently running: {snapshot.current_run_id or 'unknown'})")
            parts.append("\n".join(lines))

        if self.pinned_artifact_ids:
            pinned = (
                db.query(Artifact)
                .filter(Artifact.id.in_(self.pinned_artifact_ids))
                .all()
            )
            if pinned:
                parts.append("\n\nPinned Documents:")
                for art in pinned:
                    parts.append(
                        f"\n=== {art.name} ({art.file_path or art.artifact_type.value}) ===\n"
                        f"{art.content or '(empty)'}"
                    )
                    if art.ai_review_feedback and art.ai_review_feedback.get("document"):
                        review = art.ai_review_feedback
                        parts.append(
                            f"\n--- AI Review (quality: {review.get('overall_quality', '?')}/10, "
                            f"recommendation: {review.get('recommendation', '?')}) ---\n"
                            f"{review['document']}"
                        )

        return "\n".join(parts)

    def _build_reinject_prefix(self, db: Session) -> str:
        messages = (
            db.query(ChatMessage)
            .filter_by(project_id=self.project_id, session_id=self.session_id)
            .order_by(ChatMessage.created_at)
            .all()
        )
        if not messages:
            return ""

        lines = ["Here is our conversation history from a previous session:\n"]
        total_chars = 0
        selected = []
        for msg in reversed(messages):
            entry = f"[{msg.role.upper()}]: {msg.content}"
            if total_chars + len(entry) > _MAX_REINJECT_CHARS:
                break
            selected.append(entry)
            total_chars += len(entry)

        selected.reverse()
        lines.extend(selected)
        lines.append("\n---\n\nContinuing the conversation:")
        return "\n\n".join(lines)

    # ── Persistence ─────────────────────────────────────────────────────

    def persist_message(self, role: str, content: str):
        db = SessionLocal()
        try:
            msg = ChatMessage(
                id=str(uuid.uuid4()),
                project_id=self.project_id,
                session_id=self.session_id,
                role=role,
                content=content,
                pinned_artifacts=self.pinned_artifact_ids if self.pinned_artifact_ids else None,
            )
            db.add(msg)
            db.commit()
        except Exception:
            logger.exception("Failed to persist chat message")
            db.rollback()
        finally:
            db.close()

    # ── Generation (runs as background task) ────────────────────────────

    async def start_generation(self, message: str):
        """Persist user message and start background generation task."""
        self.persist_message("user", message)
        self._broadcast(ChatEvent(EventType.RESPONSE_START))

        self.is_generating = True
        self._generation_task = asyncio.create_task(
            self._run_generation(message)
        )

    async def _run_generation(self, message: str):
        """Background task: stream CLI output, broadcast chunks, persist result."""
        full_response = ""
        try:
            self.message_count += 1
            resume = self.message_count > 1

            system_prompt = None
            actual_message = message
            if not resume:
                db = SessionLocal()
                try:
                    system_prompt = self._build_system_prompt(db)
                    if self._needs_reinject:
                        prefix = self._build_reinject_prefix(db)
                        if prefix:
                            actual_message = f"{prefix}\n\n{message}"
                        self._needs_reinject = False
                finally:
                    db.close()

            manager = CLIManager()
            line_num = 0
            async for line in manager.generate_streaming(
                prompt=actual_message,
                working_dir=self.working_dir,
                session_id=self.session_id,
                resume=resume,
                tools=self.CHAT_TOOLS,
                system_prompt=system_prompt,
            ):
                line_num += 1
                text_chunk = ""
                try:
                    chunk = json.loads(line)
                    chunk_type = chunk.get("type")
                    if line_num <= 10:
                        logger.info(
                            "Chat line %d type=%s keys=%s",
                            line_num, chunk_type, list(chunk.keys()),
                        )
                    if chunk_type == "assistant":
                        for block in chunk.get("content", []):
                            if block.get("type") == "text":
                                text_chunk = block.get("text", "")
                    elif chunk_type == "result":
                        result_text = chunk.get("result", "")
                        if result_text and not full_response:
                            text_chunk = result_text
                except json.JSONDecodeError:
                    logger.info("Chat non-JSON line %d: %s", line_num, line[:200])
                    text_chunk = line

                if text_chunk:
                    full_response += text_chunk
                    self._broadcast(ChatEvent(
                        EventType.RESPONSE_CHUNK,
                        {"text": text_chunk},
                    ))

            logger.info(
                "Chat generation done: %d lines processed, %d chars response",
                line_num, len(full_response),
            )

        except Exception as e:
            logger.exception("Chat generation error for project %s: %s",
                             self.project_id, e)
            self._broadcast(ChatEvent(
                EventType.ERROR,
                {"message": str(e)},
            ))
        finally:
            self.is_generating = False
            if full_response:
                self.persist_message("assistant", full_response)
            self._broadcast(ChatEvent(
                EventType.RESPONSE_END,
                {"full_text": full_response},
            ))

    # ── Pin management ──────────────────────────────────────────────────

    def pin(self, artifact_id: str):
        if artifact_id not in self.pinned_artifact_ids:
            self.pinned_artifact_ids.append(artifact_id)
        self._broadcast(ChatEvent(
            EventType.PINS_UPDATED,
            {"pinned": self.pinned_artifact_ids},
        ))

    def unpin(self, artifact_id: str):
        if artifact_id in self.pinned_artifact_ids:
            self.pinned_artifact_ids.remove(artifact_id)
        self._broadcast(ChatEvent(
            EventType.PINS_UPDATED,
            {"pinned": self.pinned_artifact_ids},
        ))


# ── ChatService: manages sessions per project ──────────────────────────────


class ChatService:
    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create_session(
        self, project_id: str, working_dir: str
    ) -> ChatSession:
        if project_id not in self._sessions:
            db = SessionLocal()
            try:
                last_msg = (
                    db.query(ChatMessage)
                    .filter_by(project_id=project_id)
                    .order_by(desc(ChatMessage.created_at))
                    .first()
                )
                if last_msg:
                    session_id = last_msg.session_id
                    session = ChatSession(session_id, working_dir, project_id)
                    session._needs_reinject = True
                    last_pinned = (
                        db.query(ChatMessage)
                        .filter(
                            ChatMessage.project_id == project_id,
                            ChatMessage.session_id == session_id,
                            ChatMessage.pinned_artifacts.isnot(None),
                        )
                        .order_by(desc(ChatMessage.created_at))
                        .first()
                    )
                    if last_pinned and last_pinned.pinned_artifacts:
                        session.pinned_artifact_ids = list(last_pinned.pinned_artifacts)
                else:
                    session_id = str(uuid.uuid4())
                    session = ChatSession(session_id, working_dir, project_id)

                self._sessions[project_id] = session
                logger.info(
                    "Created chat session %s for project %s (reinject=%s)",
                    session_id, project_id, session._needs_reinject,
                )
            finally:
                db.close()
        return self._sessions[project_id]

    def get_session_messages(self, project_id: str, session_id: str) -> list[dict]:
        db = SessionLocal()
        try:
            messages = (
                db.query(ChatMessage)
                .filter_by(project_id=project_id, session_id=session_id)
                .order_by(ChatMessage.created_at)
                .all()
            )
            return [
                {
                    "role": m.role,
                    "content": m.content,
                    "pinned_artifacts": m.pinned_artifacts,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ]
        finally:
            db.close()

    def get_available_artifacts(self, project_id: str) -> list[dict]:
        db = SessionLocal()
        try:
            artifacts = (
                db.query(Artifact)
                .filter_by(project_id=project_id)
                .filter(Artifact.content.isnot(None))
                .order_by(Artifact.artifact_type, Artifact.name)
                .all()
            )
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "artifact_type": a.artifact_type.value,
                    "component_key": a.component_key,
                    "file_path": a.file_path,
                    "status": a.status.value,
                }
                for a in artifacts
            ]
        finally:
            db.close()

    def close_session(self, project_id: str):
        session = self._sessions.pop(project_id, None)
        if session:
            logger.info("Closed chat session %s", session.session_id)

    def reset_session(self, project_id: str, working_dir: str) -> ChatSession:
        old = self._sessions.get(project_id)
        if old:
            # Notify any subscribers on the old session so relay tasks can clean up
            old._broadcast(ChatEvent(EventType.SESSION_RESET))
        self.close_session(project_id)
        session_id = str(uuid.uuid4())
        session = ChatSession(session_id, working_dir, project_id)
        self._sessions[project_id] = session
        logger.info("Reset chat session to %s for project %s", session_id, project_id)
        return session


chat_service = ChatService()
