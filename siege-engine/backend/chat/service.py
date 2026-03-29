"""Chat service managing Claude CLI subprocess sessions per project."""

import logging
import uuid

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.cli.manager import CLIManager
from backend.database import SessionLocal
from backend.models import Artifact, PipelineSnapshot
from backend.models.chat import ChatMessage

logger = logging.getLogger(__name__)

# Max chars of conversation history to re-inject after session loss
_MAX_REINJECT_CHARS = 50_000


class ChatSession:
    """A single chat session backed by Claude CLI."""

    def __init__(self, session_id: str, working_dir: str, project_id: str):
        self.session_id = session_id
        self.working_dir = working_dir
        self.project_id = project_id
        self.message_count = 0
        self.pinned_artifact_ids: list[str] = []
        self._needs_reinject = False

    # All default tools except file-writing ones (Edit, Write, NotebookEdit).
    CHAT_TOOLS = "Bash,Read,Glob,Grep,WebFetch,WebSearch,Agent,TodoWrite"
    CHAT_SYSTEM_PROMPT = (
        "You have read-only access to this repository. "
        "Do NOT use Bash to create, modify, or delete any files or directories "
        "(no rm, mv, cp, touch, mkdir, sed -i, tee, redirects like > or >>, etc.). "
        "Only use Bash for read-only commands such as git log, git diff, ls, find, "
        "grep, cat, head, tail, wc, etc."
    )

    def _build_system_prompt(self, db: Session) -> str:
        """Build a system prompt with pipeline state and pinned artifact context."""
        parts = [self.CHAT_SYSTEM_PROMPT]

        # Pipeline state summary
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

        # Pinned artifact content
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
        """Build a conversation history prefix for re-injection after session loss."""
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
        # Work backwards to get the most recent messages within budget
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

    def persist_message(self, role: str, content: str):
        """Save a message to the database."""
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

    async def send_message(self, message: str):
        """Send a message and yield streaming response chunks."""
        self.message_count += 1
        resume = self.message_count > 1

        # Build system prompt with context on first message
        system_prompt = None
        actual_message = message
        if not resume:
            db = SessionLocal()
            try:
                system_prompt = self._build_system_prompt(db)
                # Re-inject history if this is a resumed DB session with a new CLI session
                if self._needs_reinject:
                    prefix = self._build_reinject_prefix(db)
                    if prefix:
                        actual_message = f"{prefix}\n\n{message}"
                    self._needs_reinject = False
            finally:
                db.close()

        manager = CLIManager()
        async for line in manager.generate_streaming(
            prompt=actual_message,
            working_dir=self.working_dir,
            session_id=self.session_id,
            resume=resume,
            tools=self.CHAT_TOOLS,
            system_prompt=system_prompt,
        ):
            yield line


class ChatService:
    """Manages chat sessions per project."""

    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create_session(
        self, project_id: str, working_dir: str
    ) -> ChatSession:
        """Get existing session for project or create a new one.

        If no in-memory session exists, check the DB for the most recent
        session and resume it (the CLI session may be gone, so mark it for
        re-injection).
        """
        if project_id not in self._sessions:
            db = SessionLocal()
            try:
                # Check for a recent DB session to resume
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
                    # Restore pinned artifacts from the most recent message that has them
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
                    session_id,
                    project_id,
                    session._needs_reinject,
                )
            finally:
                db.close()
        return self._sessions[project_id]

    def get_session_messages(self, project_id: str, session_id: str) -> list[dict]:
        """Load persisted messages for a session."""
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
        """Get artifacts available for pinning in chat."""
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
        """Remove session for a project."""
        session = self._sessions.pop(project_id, None)
        if session:
            logger.info("Closed chat session %s", session.session_id)

    def reset_session(self, project_id: str, working_dir: str) -> ChatSession:
        """Start a fresh session. Old messages stay in DB."""
        self.close_session(project_id)
        session_id = str(uuid.uuid4())
        session = ChatSession(session_id, working_dir, project_id)
        self._sessions[project_id] = session
        logger.info("Reset chat session to %s for project %s", session_id, project_id)
        return session


chat_service = ChatService()
