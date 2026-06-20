"""File-backed knowledge base.

A simple, local implementation of the knowledge store: one Markdown file per
topic under the base directory (``settings.file_path`` or ``./knowledge_base``).
Phase 4 replaces this with Redis-backed semantic memory, but the agent-facing
contract (these four functions) stays the same.
"""
from __future__ import annotations

from pathlib import Path

from schemas.agent5 import KnowledgeBaseResult
from tools.execution_lock import require_consent


def _base_dir() -> Path:
    from config import settings

    base = Path(settings.file_path) if settings.file_path else Path("knowledge_base")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _path(file_name: str) -> Path:
    name = file_name if file_name.endswith(".md") else f"{file_name}.md"
    return _base_dir() / name


def create_new_file(file_name: str, file_content: str) -> KnowledgeBaseResult:
    """Create a new knowledge file. Fails if it already exists."""
    require_consent("knowledge.create")
    path = _path(file_name)
    if path.exists():
        return KnowledgeBaseResult(
            success=False, context="", message=f"'{file_name}' already exists."
        )
    path.write_text(file_content, encoding="utf-8")
    return KnowledgeBaseResult(success=True, context=file_content, message=f"Created '{file_name}'.")


def read_file(file_name: str) -> KnowledgeBaseResult:
    """Read a knowledge file's contents."""
    path = _path(file_name)
    if not path.exists():
        return KnowledgeBaseResult(
            success=False, context="", message=f"'{file_name}' not found."
        )
    content = path.read_text(encoding="utf-8")
    return KnowledgeBaseResult(success=True, context=content, message=f"Read '{file_name}'.")


def update_file(file_name: str, file_content: str) -> KnowledgeBaseResult:
    """Overwrite a knowledge file's contents (creating it if needed)."""
    require_consent("knowledge.update")
    path = _path(file_name)
    existed = path.exists()
    path.write_text(file_content, encoding="utf-8")
    verb = "Updated" if existed else "Created"
    return KnowledgeBaseResult(success=True, context=file_content, message=f"{verb} '{file_name}'.")


def add_context(file_name: str, context: str) -> KnowledgeBaseResult:
    """Append a line of context to an existing (or new) knowledge file."""
    require_consent("knowledge.add_context")
    path = _path(file_name)
    prior = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = f"{prior.rstrip()}\n{context}\n" if prior else f"{context}\n"
    path.write_text(updated, encoding="utf-8")
    return KnowledgeBaseResult(
        success=True, context=updated, message=f"Added context to '{file_name}'."
    )
