"""Chat WebSocket endpoint for interactive Claude CLI sessions."""

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from backend.auth.service import decode_token
from backend.chat.service import chat_service
from backend.database import SessionLocal
from backend.git_manager.service import git_manager
from backend.models import Project

logger = logging.getLogger(__name__)

router = APIRouter()


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

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                msg = {"type": "message", "content": data}

            if msg.get("type") == "reset":
                chat_service.reset_session(project_id)
                session = chat_service.get_or_create_session(project_id, working_dir)
                await websocket.send_json({"type": "session_reset"})
                continue

            content = msg.get("content", "")
            if not content:
                continue

            # Stream response back
            await websocket.send_json({"type": "response_start"})

            full_response = ""
            async for line in session.send_message(content):
                # Parse stream-json format from CLI
                try:
                    chunk = json.loads(line)
                    # stream-json emits assistant/content/text blocks
                    if chunk.get("type") == "assistant":
                        for block in chunk.get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                full_response += text
                                await websocket.send_json(
                                    {
                                        "type": "response_chunk",
                                        "text": text,
                                    }
                                )
                    elif chunk.get("type") == "result":
                        # Final result message
                        result_text = chunk.get("result", "")
                        if result_text and not full_response:
                            full_response = result_text
                            await websocket.send_json(
                                {
                                    "type": "response_chunk",
                                    "text": result_text,
                                }
                            )
                except json.JSONDecodeError:
                    # Raw text fallback
                    full_response += line
                    await websocket.send_json(
                        {
                            "type": "response_chunk",
                            "text": line,
                        }
                    )

            await websocket.send_json(
                {
                    "type": "response_end",
                    "full_text": full_response,
                }
            )

    except WebSocketDisconnect:
        logger.info("Chat WebSocket disconnected for project %s", project_id)
    except Exception as e:
        logger.exception("Chat WebSocket error for project %s: %s", project_id, e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
