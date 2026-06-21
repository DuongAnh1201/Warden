"""Google Drive tools — read and write, gated where consequential.

Risk split (mirrors Gmail):

* **Reads** (:func:`list_files`, :func:`read_file`) have no side effect and are
  **not gated** — the agent may call them freely.
* **Writes** (:func:`upload_file`, :func:`update_file`, :func:`share_file`,
  :func:`delete_file`) change Drive state and call :func:`require_consent`, flowing
  through the consent gate. ``share_file`` is data egress (Tier 2); ``delete_file``
  is destructive (Tier 2).

When :data:`DEMO_MODE` is on **or** no Google credentials are available, actions are
simulated. Credentials come from the user's Workspace OAuth grant (see
``tools/google_auth.py`` and ``docs/workspace-integration/``).

Scope notes: ``list_files``/``read_file`` work with ``drive.readonly`` *or*
``drive.file``; the write tools work with ``drive.file`` (app-created files only) or
``drive``. If the granted scope is insufficient, Google returns an error which is
surfaced to the agent.
"""
from __future__ import annotations

from typing import Any

from tools import DEMO_MODE
from tools.execution_lock import require_consent


def _demo(creds: Any) -> bool:
    """Simulate when demo mode is on or we have no Google credentials yet."""
    return DEMO_MODE or creds is None


def _service(creds: Any):
    """Build a Drive v3 service client."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _as_bytes(content: str | bytes) -> bytes:
    return content if isinstance(content, bytes) else content.encode("utf-8")


# ── Reads (no side effect, NOT gated) ────────────────────────────────────────────

def list_files(query: str = "", creds: Any = None, max_results: int = 20) -> str:
    """List/search Drive files. ``query`` is a Drive query, e.g. "name contains 'notes'"."""
    if _demo(creds):
        return (
            f"[DEMO] 2 files matching {query or '*'!r}:\n"
            "  • id=demo-file-1 | 'MoneyPenny Notes.txt' | text/plain\n"
            "  • id=demo-file-2 | 'Q2 Deck' | application/vnd.google-apps.presentation"
        )
    try:
        resp = (
            _service(creds)
            .files()
            .list(
                q=query or None,
                pageSize=max_results,
                fields="files(id,name,mimeType,modifiedTime)",
            )
            .execute()
        )
        files = resp.get("files", [])
    except Exception as e:  # noqa: BLE001
        return f"Failed to list files: {e}"
    if not files:
        return f"No files matched {query or '*'!r}."
    lines = [
        f"  • id={f.get('id')} | '{f.get('name')}' | {f.get('mimeType')}" for f in files
    ]
    return f"{len(files)} files:\n" + "\n".join(lines)


def read_file(file_id: str, creds: Any = None) -> str:
    """Read a Drive file's text content (Google-native files are exported to text)."""
    if _demo(creds):
        return f"[DEMO] Contents of {file_id}:\nHello from MoneyPenny — this is a demo file."
    try:
        svc = _service(creds)
        meta = svc.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        mime = meta.get("mimeType", "")
        if mime.startswith("application/vnd.google-apps"):
            data = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
        else:
            data = svc.files().get_media(fileId=file_id).execute()
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    except Exception as e:  # noqa: BLE001
        return f"Failed to read file {file_id}: {e}"
    return f"Contents of '{meta.get('name')}' ({file_id}):\n{text}"


# ── Writes (state-changing, GATED via require_consent) ───────────────────────────

def upload_file(
    name: str,
    content: str | bytes,
    creds: Any = None,
    mime_type: str = "text/plain",
    folder_id: str = "",
) -> str:
    """Create a new file in Drive. Returns a message including ``file_id=<id>``."""
    require_consent("drive.upload")
    if _demo(creds):
        return f"[DEMO] Created '{name}' in Drive. file_id=demo-{abs(hash(name)) % 10**8:08d}"
    try:
        from googleapiclient.http import MediaInMemoryUpload

        metadata: dict = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]
        media = MediaInMemoryUpload(_as_bytes(content), mimetype=mime_type, resumable=False)
        created = (
            _service(creds)
            .files()
            .create(body=metadata, media_body=media, fields="id,name,webViewLink")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return (
        f"Created '{created.get('name')}' in Drive. file_id={created.get('id')} "
        f"link={created.get('webViewLink', '')}"
    )


FOLDER_MIME = "application/vnd.google-apps.folder"


def create_folder(name: str, creds: Any = None, parent_id: str = "") -> str:
    """Create a new folder in Drive. Returns a message including ``folder_id=<id>``.

    A Drive folder is a file with the folder mime type and no media body.
    """
    require_consent("drive.create_folder")
    if _demo(creds):
        return f"[DEMO] Created folder '{name}' in Drive. folder_id=demo-{abs(hash(name)) % 10**8:08d}"
    try:
        metadata: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            metadata["parents"] = [parent_id]
        created = (
            _service(creds)
            .files()
            .create(body=metadata, fields="id,name,webViewLink")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return (
        f"Created folder '{created.get('name')}' in Drive. folder_id={created.get('id')} "
        f"link={created.get('webViewLink', '')}"
    )


def update_file(file_id: str, content: str | bytes, creds: Any = None, mime_type: str = "text/plain") -> str:
    """Overwrite the content of an existing Drive file."""
    require_consent("drive.update")
    if _demo(creds):
        return f"[DEMO] Updated file {file_id}."
    try:
        from googleapiclient.http import MediaInMemoryUpload

        media = MediaInMemoryUpload(_as_bytes(content), mimetype=mime_type, resumable=False)
        _service(creds).files().update(fileId=file_id, media_body=media).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Updated file {file_id}."


def share_file(
    file_id: str,
    email: str,
    role: str = "reader",
    creds: Any = None,
    send_notification: bool = False,
) -> str:
    """Share a Drive file with an email address. This is external data egress."""
    require_consent("drive.share")
    if _demo(creds):
        return f"[DEMO] Shared file {file_id} with {email} as {role}."
    try:
        _service(creds).permissions().create(
            fileId=file_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=send_notification,
            fields="id",
        ).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Shared file {file_id} with {email} as {role}."


def delete_file(file_id: str, creds: Any = None, trash: bool = True) -> str:
    """Delete a Drive file. By default moves to Trash (recoverable)."""
    require_consent("drive.delete")
    if _demo(creds):
        verb = "Trashed" if trash else "Permanently deleted"
        return f"[DEMO] {verb} file {file_id}."
    try:
        svc = _service(creds)
        if trash:
            svc.files().update(fileId=file_id, body={"trashed": True}).execute()
            return f"Moved file {file_id} to Trash."
        svc.files().delete(fileId=file_id).execute()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e
    return f"Permanently deleted file {file_id}."
