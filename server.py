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
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

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

    # ── Google Workspace OAuth ────────────────────────────────────────────────

    @app.get("/api/workspace/status")
    async def workspace_status() -> dict:
        from tools.google_auth import granted_scopes, SCOPE_CATALOG
        scopes = granted_scopes()
        connected: dict[str, str] = {}
        for surface, spec in SCOPE_CATALOG.items():
            for level, info in spec["levels"].items():
                if level == "off":
                    continue
                if all(s in scopes for s in info["scopes"]) and info["scopes"]:
                    connected[surface] = level
                    break
            else:
                connected[surface] = "off"
        return {"connected": bool(scopes), "surfaces": connected, "scopes": scopes}

    @app.get("/api/workspace/connect")
    async def workspace_connect(
        drive: str = "file",
        gmail: str = "read",
        calendar: str = "manage",
    ):
        """Start the Google OAuth flow. Redirects the browser to Google's consent screen."""
        from config import settings
        from tools.google_auth import resolve_scopes

        if not settings.google_client_id or not settings.google_client_secret:
            return {"error": "Google OAuth not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing)"}

        selection = {"drive": drive, "gmail": gmail, "calendar": calendar}
        try:
            scopes = resolve_scopes(selection)
        except ValueError as e:
            return {"error": str(e)}

        if not scopes:
            return {"error": "All surfaces set to off — nothing to connect."}

        from google_auth_oauthlib.flow import Flow

        client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        }
        flow = Flow.from_client_config(client_config, scopes=scopes)
        flow.redirect_uri = settings.google_redirect_uri

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return RedirectResponse(auth_url)

    @app.get("/oauth2callback")
    async def workspace_callback(request: Request):
        """Google redirects here after the user approves. Saves the token and closes."""
        from config import settings
        from tools.google_auth import save_token

        code = request.query_params.get("code")
        error = request.query_params.get("error")

        if error:
            return HTMLResponse(f"<h2>OAuth error: {error}</h2><p>Close this tab and try again.</p>")
        if not code:
            return HTMLResponse("<h2>Missing code</h2><p>No authorization code received.</p>")

        from google_auth_oauthlib.flow import Flow

        client_config = {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.google_redirect_uri],
            }
        }
        # Re-derive scopes from the state — use broadest set; granted_scopes() will reflect actual
        from tools.google_auth import SCOPE_CATALOG
        all_scopes = [s for spec in SCOPE_CATALOG.values()
                      for lvl in spec["levels"].values() for s in lvl["scopes"]]
        all_scopes = sorted(set(all_scopes))

        flow = Flow.from_client_config(client_config, scopes=all_scopes)
        flow.redirect_uri = settings.google_redirect_uri

        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            logger.exception("OAuth token exchange failed")
            return HTMLResponse(f"<h2>Token exchange failed</h2><pre>{exc}</pre>")

        creds = flow.credentials
        save_token({
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or all_scopes),
        })
        logger.info("[workspace] OAuth complete — token saved")
        return HTMLResponse(
            "<h2>✓ Connected to Google Workspace</h2>"
            "<p>Drive, Gmail and Calendar are now live. Close this tab and refresh MoneyPenny.</p>"
        )

    @app.delete("/api/workspace/disconnect")
    async def workspace_disconnect() -> dict:
        from tools.google_auth import revoke
        removed = revoke()
        return {"disconnected": removed}

    # ── WebSocket ─────────────────────────────────────────────────────────────

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
