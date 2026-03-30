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

    # Shared mutable state so the relay and command handler stay in sync
    # after session resets (which swap the session + queue).
    shared: dict = {
        "session": session,
        "sub_id": sub_id,
        "queue": event_queue,
    }

    try:
        # Send persisted history (include partial response if mid-generation)
        history = chat_service.get_session_messages(project_id, session.session_id)
        if session.is_generating and session._partial_response:
            history.append(
                {
                    "role": "assistant",
                    "content": session._partial_response,
                    "pinned_artifacts": None,
                    "created_at": None,
                }
            )
        await websocket.send_json(
            {
                "type": "history",
                "messages": history,
                "session_id": session.session_id,
            }
        )

        # Send current pin state
        await websocket.send_json(
            {
                "type": "pins_updated",
                "pinned": session.pinned_artifact_ids,
            }
        )

        # If generation is in progress, tell the client
        if session.is_generating:
            logger.info("Chat session %s still generating, notifying client", session.session_id)
            await websocket.send_json({"type": "response_generating"})
        else:
            logger.info("Chat session %s idle on connect (is_generating=False)", session.session_id)

        # Run two concurrent tasks:
        # 1. Relay events from session → WS
        # 2. Receive commands from WS → session
        await asyncio.gather(
            _relay_events(websocket, shared),
            _handle_commands(websocket, shared, project_id),
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
        shared["session"].unsubscribe(shared["sub_id"])


async def _relay_events(websocket: WebSocket, shared: dict):
    """Forward session events to the WebSocket client.

    Uses ``shared['queue']`` so that a session reset (which swaps the queue)
    is picked up automatically on the next iteration.
    """
    while True:
        current_queue = shared["queue"]
        event = await current_queue.get()
        # After a session reset the queue reference is swapped.  If we just
        # woke up from an *old* queue, discard the stale event — the reset
        # handler already pushed SESSION_RESET into the new queue for us.
        if current_queue is not shared["queue"]:
            continue
        await websocket.send_json(event.to_json())


async def _handle_commands(
    websocket: WebSocket,
    shared: dict,
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
        session: ChatSession = shared["session"]

        if msg_type == "check_generating":
            if not session.is_generating:
                history = chat_service.get_session_messages(project_id, session.session_id)
                await websocket.send_json(
                    {
                        "type": "generation_complete",
                        "messages": history,
                    }
                )
            continue

        if msg_type == "reset":
            old_session = shared["session"]
            old_sub_id = shared["sub_id"]
            old_queue = shared["queue"]

            # reset_session broadcasts SESSION_RESET on the old session's bus
            # (our old subscriber still receives it).
            new_session = chat_service.reset_session(project_id, old_session.working_dir)

            # Unsubscribe from old session *after* the broadcast above
            old_session.unsubscribe(old_sub_id)

            # Subscribe to the new session so future events reach the relay
            new_sub_id, new_queue = new_session.subscribe()
            shared["session"] = new_session
            shared["sub_id"] = new_sub_id
            shared["queue"] = new_queue

            # Queue SESSION_RESET on the new queue so the relay sends it
            new_queue.put_nowait(ChatEvent(EventType.SESSION_RESET))

            # Unblock the relay if it's stuck on the old queue
            old_queue.put_nowait(ChatEvent(EventType.SESSION_RESET))
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
