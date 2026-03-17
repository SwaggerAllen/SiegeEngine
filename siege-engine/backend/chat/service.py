"""Chat service managing Claude CLI subprocess sessions per project."""

import asyncio
import json
import logging
import uuid

from backend.cli.manager import CLIManager
from backend.config import settings

logger = logging.getLogger(__name__)


class ChatSession:
    """A single chat session backed by Claude CLI."""

    def __init__(self, session_id: str, working_dir: str):
        self.session_id = session_id
        self.working_dir = working_dir
        self.message_count = 0

    # All default tools except file-writing ones (Edit, Write, NotebookEdit).
    CHAT_TOOLS = "Bash,Read,Glob,Grep,WebFetch,WebSearch,Agent,TodoWrite"
    CHAT_SYSTEM_PROMPT = (
        "You have read-only access to this repository. "
        "Do NOT use Bash to create, modify, or delete any files or directories "
        "(no rm, mv, cp, touch, mkdir, sed -i, tee, redirects like > or >>, etc.). "
        "Only use Bash for read-only commands such as git log, git diff, ls, find, "
        "grep, cat, head, tail, wc, etc."
    )

    async def send_message(self, message: str):
        """Send a message and yield streaming response chunks."""
        self.message_count += 1
        resume = self.message_count > 1

        manager = CLIManager()
        async for line in manager.generate_streaming(
            prompt=message,
            working_dir=self.working_dir,
            session_id=self.session_id,
            resume=resume,
            tools=self.CHAT_TOOLS,
            system_prompt=self.CHAT_SYSTEM_PROMPT if not resume else None,
        ):
            yield line


class ChatService:
    """Manages chat sessions per project."""

    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create_session(
        self, project_id: str, working_dir: str
    ) -> ChatSession:
        """Get existing session for project or create a new one."""
        if project_id not in self._sessions:
            session_id = str(uuid.uuid4())
            self._sessions[project_id] = ChatSession(session_id, working_dir)
            logger.info(
                "Created chat session %s for project %s",
                session_id, project_id,
            )
        return self._sessions[project_id]

    def close_session(self, project_id: str):
        """Remove session for a project."""
        session = self._sessions.pop(project_id, None)
        if session:
            logger.info("Closed chat session %s", session.session_id)

    def reset_session(self, project_id: str):
        """Force a new session for a project (new conversation)."""
        self.close_session(project_id)


chat_service = ChatService()
