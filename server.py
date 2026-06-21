"""MoneyPenny backend server — Phase 2.

FastAPI + WebSocket bridge between the browser and the Pydantic AI orchestrator.

Run:
    uv run python server.py
    # WebSocket: ws://localhost:8765/ws
    # Health:    http://localhost:8765/health
    # Ledger:    http://localhost:8765/api/ledger
"""
from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from backend.protocol import serialize_ledger_entry
from backend.session import AgentSession
from observability.phoenix import setup_observability
from tools.ledger import get_ledger

logger = logging.getLogger(__name__)

HOST = os.getenv("SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", os.getenv("SERVER_PORT", "8765")))


def create_app() -> FastAPI:
    setup_observability()

    app = FastAPI(title="MoneyPenny", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "moneypenny"}

    @app.get("/api/ledger")
    async def ledger_history(limit: int = 20) -> dict:
        entries = await get_ledger().history(limit=min(limit, 100))
        return {"entries": [serialize_ledger_entry(e) for e in entries]}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        session = AgentSession(websocket)
        await session.run()

    return app


app = create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info("MoneyPenny server listening on %s:%s (ws /ws)", HOST, PORT)
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
