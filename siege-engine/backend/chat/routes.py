"""Chat WebSocket endpoint and REST routes for interactive Claude CLI sessions."""

import json
import logging

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from backend.auth.routes import get_current_user
from backend.auth.service import decode_token
from backend.chat.service import chat_service
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

    # Send persisted history on connect
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

    # If a response is still generating from a previous connection, tell the client
    if session.is_generating:
        await websocket.send_json({"type": "response_generating"})

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                msg = {"type": "message", "content": data}

            msg_type = msg.get("type")

            if msg_type == "check_generating":
                # Client polling for generation completion after reconnect
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
                session = chat_service.reset_session(project_id, working_dir)
                await websocket.send_json({
                    "type": "session_reset",
                    "session_id": session.session_id,
                })
                continue

            if msg_type == "pin":
                artifact_id = msg.get("artifact_id")
                if artifact_id and artifact_id not in session.pinned_artifact_ids:
                    session.pinned_artifact_ids.append(artifact_id)
                await websocket.send_json({
                    "type": "pins_updated",
                    "pinned": session.pinned_artifact_ids,
                })
                continue

            if msg_type == "unpin":
                artifact_id = msg.get("artifact_id")
                if artifact_id and artifact_id in session.pinned_artifact_ids:
                    session.pinned_artifact_ids.remove(artifact_id)
                await websocket.send_json({
                    "type": "pins_updated",
                    "pinned": session.pinned_artifact_ids,
                })
                continue

            content = msg.get("content", "")
            if not content:
                continue

            # Persist user message
            session.persist_message("user", content)

            # Stream response back
            full_response = ""
            ws_disconnected = False
            session.is_generating = True
            try:
                await websocket.send_json({"type": "response_start"})
            except Exception:
                ws_disconnected = True

            async for line in session.send_message(content):
                # Parse stream-json format from CLI
                text_chunk = ""
                try:
                    chunk = json.loads(line)
                    if chunk.get("type") == "assistant":
                        for block in chunk.get("content", []):
                            if block.get("type") == "text":
                                text_chunk = block.get("text", "")
                    elif chunk.get("type") == "result":
                        result_text = chunk.get("result", "")
                        if result_text and not full_response:
                            text_chunk = result_text
                except json.JSONDecodeError:
                    text_chunk = line

                if text_chunk:
                    full_response += text_chunk
                    if not ws_disconnected:
                        try:
                            await websocket.send_json(
                                {"type": "response_chunk", "text": text_chunk}
                            )
                        except Exception:
                            ws_disconnected = True
                            logger.info(
                                "Chat WS disconnected mid-stream for project %s, "
                                "continuing CLI to persist response",
                                project_id,
                            )

            # Always persist the response, even if WS disconnected
            session.is_generating = False
            if full_response:
                session.persist_message("assistant", full_response)

            if not ws_disconnected:
                await websocket.send_json(
                    {"type": "response_end", "full_text": full_response}
                )

            if ws_disconnected:
                # Exit the message loop — WS is dead
                break

    except WebSocketDisconnect:
        logger.info("Chat WebSocket disconnected for project %s", project_id)
    except Exception as e:
        logger.exception("Chat WebSocket error for project %s: %s", project_id, e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
