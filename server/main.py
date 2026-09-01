"""FastAPI app: serves the control panel + OBS display page, exposes the
config/start/stop REST API, and fans out pipeline events over WebSocket.

Run with: uvicorn server.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audio_capture import list_input_devices
from .config import ConfigStore, load_default_config
from .pipeline import Pipeline
from .ws_hub import WSHub

load_dotenv()
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"

app = FastAPI(title="Live Translation")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

config_store = ConfigStore(load_default_config(BASE_DIR / "config" / "default.yaml"))
hub = WSHub()
pipeline = Pipeline(config_store, hub)


@app.get("/")
async def control_panel():
    return FileResponse(WEB_DIR / "control.html")


@app.get("/display")
async def display_page():
    return FileResponse(WEB_DIR / "display.html")


@app.get("/api/devices")
async def api_devices():
    return list_input_devices()


@app.get("/api/config")
async def api_get_config():
    return config_store.get().model_dump()


@app.patch("/api/config")
async def api_patch_config(patch: dict = Body(...)):
    cfg = config_store.update(patch)
    await hub.broadcast({"type": "config", **cfg.model_dump()})
    return cfg.model_dump()


@app.get("/api/status")
async def api_status():
    return {"running": pipeline.running}


@app.post("/api/start")
async def api_start():
    try:
        await pipeline.start()
    except Exception as exc:  # surfaced to the control panel, e.g. missing API key
        await hub.broadcast({"type": "status", "state": "error", "message": str(exc)})
        raise
    return {"running": pipeline.running}


@app.post("/api/stop")
async def api_stop():
    await pipeline.stop()
    return {"running": pipeline.running}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    await ws.send_text(json.dumps({"type": "config", **config_store.get().model_dump()}))
    await ws.send_text(
        json.dumps({"type": "status", "state": "listening" if pipeline.running else "idle"})
    )
    try:
        while True:
            # The client doesn't send anything meaningful; this just keeps
            # the connection open and lets us notice a disconnect promptly.
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)
