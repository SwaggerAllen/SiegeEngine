"""Chat WebSocket endpoint and REST routes for interactive Claude CLI sessions.

The WS handler is a stateless subscriber: it connects to the ChatSession's
event bus, relays events to the client, and forwards client commands to the
session. Generation runs as a background asyncio task in the session, fully
decoupled from any particular WS connection.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from backend.auth.routes import get_current_user
from backend.auth.service import decode_token
from backend.chat.service import ChatEvent, ChatSession, EventType, chat_service
from backend.database import SessionLocal
from backend.git_manager.service import git_manager
from backend.models import Project

logger = logging.getLogger(__name__)

router = APIRouter()


# ──── REST endpoints ────


@router.get("/{project_id}/artifacts")
async def get_chat_artifacts(project_id: str, user=Depends(get_current_user)):
    """List artifacts available for pinning in chat context."""
    return chat_service.get_available_artifacts(project_id)


# ──── WebSocket endpoint ────


@router.websocket("/{project_id}")
async def chat_websocket(
    websocket: WebSocket,
    project_id: str,
    token: str = Query(...),
):
    # Authenticate
    try:
        decode_token(token)
    except (JWTError, Exception):
        await websocket.close(code=4001, reason="Invalid token")
        return

    # Look up project's git repo path
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project:
            await websocket.close(code=4004, reason="Project not found")
            return
        working_dir = str(git_manager.base_path / project_id)
    finally:
        db.close()

    await websocket.accept()
    logger.info("Chat WebSocket connected for project %s", project_id)

    session = chat_service.get_or_create_session(project_id, working_dir)

    # Subscribe to session's event bus
    sub_id, event_queue = session.subscribe()

    try:
        # Send persisted history
        history = chat_service.get_session_messages(project_id, session.session_id)
        await websocket.send_json({
            "type": "history",
            "messages": history,
            "session_id": session.session_id,
        })

        # Send current pin state
        await websocket.send_json({
            "type": "pins_updated",
            "pinned": session.pinned_artifact_ids,
        })

        # If generation is in progress, tell the client
        if session.is_generating:
            logger.info("Chat session %s still generating, notifying client", session.session_id)
            await websocket.send_json({"type": "response_generating"})

        # Run two concurrent tasks:
        # 1. Relay events from session → WS
        # 2. Receive commands from WS → session
        await asyncio.gather(
            _relay_events(websocket, event_queue),
            _handle_commands(websocket, session, project_id),
        )

    except WebSocketDisconnect:
        logger.info("Chat WebSocket disconnected for project %s", project_id)
    except Exception as e:
        logger.exception("Chat WebSocket error for project %s: %s", project_id, e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        session.unsubscribe(sub_id)


async def _relay_events(websocket: WebSocket, queue: asyncio.Queue[ChatEvent]):
    """Forward session events to the WebSocket client."""
    while True:
        event = await queue.get()
        await websocket.send_json(event.to_json())


async def _handle_commands(
    websocket: WebSocket,
    session: ChatSession,
    project_id: str,
):
    """Receive commands from the WS client and forward to the session."""
    while True:
        raw = await websocket.receive_text()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            msg = {"type": "message", "content": raw}

        msg_type = msg.get("type")

        if msg_type == "check_generating":
            if not session.is_generating:
                history = chat_service.get_session_messages(
                    project_id, session.session_id
                )
                await websocket.send_json({
                    "type": "generation_complete",
                    "messages": history,
                })
            continue

        if msg_type == "reset":
            # reset_session broadcasts SESSION_RESET on old session's event bus
            session = chat_service.reset_session(project_id, session.working_dir)
            continue

        if msg_type == "pin":
            artifact_id = msg.get("artifact_id")
            if artifact_id:
                session.pin(artifact_id)
            continue

        if msg_type == "unpin":
            artifact_id = msg.get("artifact_id")
            if artifact_id:
                session.unpin(artifact_id)
            continue

        content = msg.get("content", "")
        if not content:
            continue

        # Start generation as a background task in the session
        await session.start_generation(content)
