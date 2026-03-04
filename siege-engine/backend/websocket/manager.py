from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[project_id].add(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket):
        self.connections[project_id].discard(websocket)

    async def broadcast(self, project_id: str, event: dict):
        dead = []
        for ws in self.connections[project_id]:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections[project_id].discard(ws)


ws_manager = ConnectionManager()
