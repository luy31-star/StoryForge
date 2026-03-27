from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/workflow/{workflow_id}")
async def workflow_ws(websocket: WebSocket, workflow_id: str) -> None:
    await websocket.accept()
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "workflow_id": workflow_id,
                    "message": "WebSocket 已连接（占位）",
                }
            )
        )
        while True:
            raw = await websocket.receive_text()
            await websocket.send_text(
                json.dumps({"type": "echo", "workflow_id": workflow_id, "echo": raw})
            )
    except WebSocketDisconnect:
        return
