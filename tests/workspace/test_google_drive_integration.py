"""REAL Google Drive integration test — opt-in, hits your actual Drive.

This is skipped by default. It only runs when ALL of these are true:

  1. ``RUN_GOOGLE_INTEGRATION=1`` is set (explicit opt-in),
  2. demo mode is OFF (``DESIR_DEMO=0``), and
  3. you've connected Workspace with a Drive scope (token on disk).

How to run it (PowerShell):

    # one-time: enable the Drive API + set OAuth client, then connect with a Drive scope
    $env:GOOGLE_CLIENT_ID="..."; $env:GOOGLE_CLIENT_SECRET="..."
    $env:DESIR_DEMO="0"
    uv run python run_text.py --connect      # choose Drive: "file" (least privilege) is enough

    # then run the live round-trip
    $env:RUN_GOOGLE_INTEGRATION="1"; $env:DESIR_DEMO="0"
    uv run pytest tests/workspace/test_google_drive_integration.py -v -s

What it does (and cleans up after itself):
  create a file  ->  read it back  ->  update it  ->  read again  ->  move to Trash.

The ``drive.file`` scope (least privilege) is sufficient: the test only touches the
single file it creates. Sharing is NOT exercised here (it would email a real person);
see ``test_share_roundtrip`` which is separately gated on ``GOOGLE_TEST_SHARE_EMAIL``.
"""
from __future__ import annotations

import os
import re
import uuid

import pytest

from tests.workspace._integration import live_consent, require_live_drive

pytestmark = pytest.mark.integration


def _file_id(message: str) -> str:
    m = re.search(r"file_id=(\S+)", message)
    assert m, f"no file_id in tool output: {message!r}"
    return m.group(1)


def test_drive_roundtrip():
    """create -> read -> update -> read -> trash, against the real Drive API."""
    creds = require_live_drive()
    from tools.google_drive import delete_file, read_file, update_file, upload_file

    name = f"moneypenny-integration-{uuid.uuid4().hex[:8]}.txt"
    file_id = None
    try:
        with live_consent("drive.upload"):
            created = upload_file(name, "hello from the integration test", creds=creds)
        file_id = _file_id(created)
        assert file_id

        body = read_file(file_id, creds=creds)
        assert "hello from the integration test" in body

        with live_consent("drive.update"):
            update_file(file_id, "updated by the integration test", creds=creds)

        body2 = read_file(file_id, creds=creds)
        assert "updated by the integration test" in body2
    finally:
        if file_id:
            with live_consent("drive.delete"):
                delete_file(file_id, creds=creds, trash=True)


@pytest.mark.skipif(
    not os.getenv("GOOGLE_TEST_SHARE_EMAIL"),
    reason="set GOOGLE_TEST_SHARE_EMAIL to a real address to test sharing (data egress)",
)
def test_share_roundtrip():
    """Create a file, share it (no notification email), then trash it."""
    creds = require_live_drive()
    from tools.google_drive import delete_file, share_file, upload_file

    target = os.environ["GOOGLE_TEST_SHARE_EMAIL"]
    name = f"moneypenny-share-{uuid.uuid4().hex[:8]}.txt"
    file_id = None
    try:
        with live_consent("drive.upload"):
            created = upload_file(name, "share test", creds=creds)
        file_id = _file_id(created)

        with live_consent("drive.share"):
            msg = share_file(file_id, target, role="reader", creds=creds)
        assert target in msg
    finally:
        if file_id:
            with live_consent("drive.delete"):
                delete_file(file_id, creds=creds, trash=True)
