"""Schemas for the Drive agent (read + write).

Listing and reading files have no side effect. Writing (upload, update, share,
delete) changes Drive state and flows through the consent gate.
"""
from __future__ import annotations

from pydantic import BaseModel


class DriveSearchRequest(BaseModel):
    query: str = ""
    """Drive query, e.g. "name contains 'notes'", "mimeType='application/pdf'"."""
    max_results: int = 20


class DriveFileRequest(BaseModel):
    """Args for read/write actions. Only the fields relevant to the action are used."""

    file_id: str = ""
    name: str = ""
    content: str = ""
    mime_type: str = "text/plain"
    folder_id: str = ""
    # Sharing
    email: str = ""
    role: str = "reader"


class DriveResult(BaseModel):
    success: bool
    message: str
