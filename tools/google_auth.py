"""Google Workspace OAuth — the *connection consent* layer.

This is Phase A of ``docs/workspace-integration/``: it lets the user decide, at
connect time, **which surfaces** (Drive / Gmail / Calendar) and **how much** access
to grant — then runs the OAuth flow and stores the resulting refresh token
**encrypted at rest**. The stored credentials are later injected into
``OrchestratorDeps.workspace_creds`` so the Calendar/Gmail tools make real calls.

Connection consent is *not* action consent. Even after the user connects, every
consequential action still passes through the per-action consent gate
(``require_consent`` / ``gate``). Granting Gmail does not authorize sending.

Design notes
------------
* The **scope catalog** (:data:`SCOPE_CATALOG`) is the single source of truth for the
  user-facing menu and for mapping a chosen *level* to Google OAuth scopes.
* The token store serializes a small JSON blob and encrypts it with Fernet, keyed
  from ``settings.workspace_token_key`` (falling back to ``settings.consent_secret``).
* Google / cryptography imports are lazy so the module is cheap to import and the
  pure-logic helpers (scope resolution) need no third-party deps.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

# ── Scope catalog (single source of truth for the menu + scope resolution) ───────

SCOPE_CATALOG: dict[str, dict[str, Any]] = {
    "drive": {
        "label": "Google Drive",
        "default": "file",
        "levels": {
            "off":  {"label": "Off — no Drive access", "scopes": []},
            "file": {"label": "App files only — only files MoneyPenny creates",
                     "scopes": ["https://www.googleapis.com/auth/drive.file"]},
            "read": {"label": "Read existing files — search/read your Drive",
                     "scopes": ["https://www.googleapis.com/auth/drive.readonly"]},
            "full": {"label": "Full Drive access (broadest — least safe)",
                     "scopes": ["https://www.googleapis.com/auth/drive"]},
        },
    },
    "gmail": {
        "label": "Gmail",
        "default": "read",
        "levels": {
            "off":    {"label": "Off — no Gmail access", "scopes": []},
            "read":   {"label": "Read only — search & read your inbox",
                       "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]},
            "triage": {"label": "Read & triage — label, archive, draft, trash (no sending)",
                       "scopes": ["https://www.googleapis.com/auth/gmail.modify"]},
            "send":   {"label": "Read, triage & send",
                       "scopes": ["https://www.googleapis.com/auth/gmail.modify",
                                  "https://www.googleapis.com/auth/gmail.send"]},
        },
    },
    "calendar": {
        "label": "Google Calendar",
        "default": "manage",
        "levels": {
            "off":    {"label": "Off — no Calendar access", "scopes": []},
            "read":   {"label": "Read only — view events & free/busy",
                       "scopes": ["https://www.googleapis.com/auth/calendar.readonly"]},
            "manage": {"label": "Read & manage — create/update/delete events",
                       "scopes": ["https://www.googleapis.com/auth/calendar.events",
                                  "https://www.googleapis.com/auth/calendar.readonly"]},
        },
    },
}


def resolve_scopes(selection: dict[str, str]) -> list[str]:
    """Map a ``{surface: level}`` selection to a sorted, de-duplicated scope list.

    Raises ``ValueError`` for unknown surfaces or levels (fail closed — never grant
    a scope we don't recognize).
    """
    scopes: set[str] = set()
    for surface, level in selection.items():
        if surface not in SCOPE_CATALOG:
            raise ValueError(f"Unknown surface: {surface!r}")
        levels = SCOPE_CATALOG[surface]["levels"]
        if level not in levels:
            raise ValueError(f"Unknown level {level!r} for {surface!r}")
        scopes.update(levels[level]["scopes"])
    return sorted(scopes)


def summarize_selection(selection: dict[str, str]) -> str:
    """Human-readable one-liner describing what the user chose (for logs/ledger)."""
    parts = []
    for surface, level in selection.items():
        label = SCOPE_CATALOG.get(surface, {}).get("levels", {}).get(level, {}).get("label", level)
        parts.append(f"{SCOPE_CATALOG.get(surface, {}).get('label', surface)}: {label}")
    return "; ".join(parts) if parts else "no access"


# ── Interactive scope menu (the user decides) ────────────────────────────────────

def prompt_scope_selection(input_fn=input, print_fn=print) -> dict[str, str]:
    """Present the per-surface menu and collect the user's choices.

    ``input_fn``/``print_fn`` are injectable for testing. Empty input picks the
    surface's default (least-privilege-leaning). Returns a ``{surface: level}`` dict.
    """
    selection: dict[str, str] = {}
    print_fn("\nConnect Google Workspace — choose how much access to grant.")
    print_fn("Press Enter to accept the [default]. Choose 'off' to skip a surface.\n")
    for surface, spec in SCOPE_CATALOG.items():
        print_fn(f"== {spec['label']} ==")
        level_keys = list(spec["levels"].keys())
        for i, key in enumerate(level_keys, 1):
            mark = " [default]" if key == spec["default"] else ""
            print_fn(f"  {i}. {key} — {spec['levels'][key]['label']}{mark}")
        choice = (input_fn(f"  Select for {spec['label']} [{spec['default']}]: ") or "").strip()
        level = spec["default"]
        if choice:
            if choice.isdigit() and 1 <= int(choice) <= len(level_keys):
                level = level_keys[int(choice) - 1]
            elif choice in spec["levels"]:
                level = choice
            else:
                print_fn(f"  (unrecognized '{choice}', using default '{level}')")
        selection[surface] = level
        print_fn("")
    return selection


# ── Encrypted token store ────────────────────────────────────────────────────────

def _key_material() -> str:
    from config import settings

    return getattr(settings, "workspace_token_key", "") or settings.consent_secret


def _fernet(key_material: str | None = None):
    from cryptography.fernet import Fernet

    material = key_material or _key_material()
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _token_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    from config import settings

    return Path(settings.workspace_token_path)


def save_token(data: dict, *, path: str | Path | None = None, key: str | None = None) -> Path:
    """Encrypt and persist the token blob (refresh_token, scopes, client info…)."""
    p = _token_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = _fernet(key).encrypt(json.dumps(data).encode("utf-8"))
    p.write_bytes(blob)
    return p


def load_token(*, path: str | Path | None = None, key: str | None = None) -> dict | None:
    """Decrypt and return the stored token blob, or ``None`` if not connected."""
    p = _token_path(path)
    if not p.exists():
        return None
    try:
        return json.loads(_fernet(key).decrypt(p.read_bytes()).decode("utf-8"))
    except Exception:  # noqa: BLE001 — corrupt/incompatible token => treat as not connected
        return None


def delete_token(*, path: str | Path | None = None) -> bool:
    """Remove the local token file. Returns True if a file was deleted."""
    p = _token_path(path)
    if p.exists():
        p.unlink()
        return True
    return False


def granted_scopes(*, path: str | Path | None = None, key: str | None = None) -> list[str]:
    """Scopes currently granted (empty if not connected)."""
    data = load_token(path=path, key=key)
    return list(data.get("scopes", [])) if data else []


# ── OAuth flow + credential provider (require real Google client creds) ──────────

def connect(selection: dict[str, str], *, open_browser: bool = True) -> Any:
    """Run the installed-app OAuth flow for the chosen scopes and store the token.

    Returns google credentials. Raises ``RuntimeError`` if the OAuth client isn't
    configured (``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET``).
    """
    from config import settings

    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError(
            "Google OAuth client not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET to connect a real account."
        )
    scopes = resolve_scopes(selection)
    if not scopes:
        raise RuntimeError("No scopes selected — nothing to connect.")

    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
    creds = flow.run_local_server(port=0, open_browser=open_browser)

    save_token(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or scopes),
        }
    )
    return creds


def build_credentials(data: dict) -> Any:
    """Reconstruct google credentials from a stored token blob."""
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )


def get_workspace_credentials(*, path: str | Path | None = None, key: str | None = None) -> Any | None:
    """Load stored credentials for injection into ``OrchestratorDeps.workspace_creds``.

    Returns ``None`` when not connected, so tools transparently fall back to demo
    mode. Refreshes an expired access token when a refresh token is present.
    """
    data = load_token(path=path, key=key)
    if not data:
        return None
    creds = build_credentials(data)
    try:
        if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            data["token"] = creds.token
            save_token(data, path=path, key=key)
    except Exception:  # noqa: BLE001 — refresh failure => caller will get demo fallback
        return None
    return creds


def revoke(*, path: str | Path | None = None, key: str | None = None) -> bool:
    """Revoke the grant: best-effort network revoke + delete the local token.

    Returns True if a local token was removed. This is the connection-level "kill
    switch" referenced in the consent architecture.
    """
    data = load_token(path=path, key=key)
    if data and data.get("refresh_token"):
        try:
            import httpx

            httpx.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": data["refresh_token"]},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
        except Exception:  # noqa: BLE001 — local delete still proceeds
            pass
    return delete_token(path=path)


# ── Lifecycle ledger logging ─────────────────────────────────────────────────────

async def log_workspace_event(ledger, event_type: str, summary: str, detail: dict | None = None) -> None:
    """Record a connection-lifecycle event (connect/upgrade/revoke) in the ledger.

    Modeled as an approved+executed action so the audit trail answers "what access
    did I grant, and when?" alongside ordinary action history.
    """
    from schemas.consent import ActionDecision, ActionRequest

    req = ActionRequest(
        action_type=event_type,  # type: ignore[arg-type]
        agent="workspace_auth",
        summary=summary,
        payload=detail or {},
    )
    await ledger.record_request(req)
    await ledger.record_decision(ActionDecision(action_id=req.action_id, decision="approve"))
    await ledger.record_outcome(req.action_id, "executed", summary)
