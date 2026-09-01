"""Broadcasts pipeline events (partial transcript, committed chunk,
status, config) to every connected browser — the control panel and the
OBS display page both connect here over the same WebSocket."""
from __future__ import annotations

import json

from fastapi import WebSocket


class WSHub:
    def __init__(self):
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        payload = json.dumps(message)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
