"""Linter tool models."""

from __future__ import annotations

from pydantic import BaseModel


class LinterFinding(BaseModel):
    tool: str
    severity: str  # "error", "warning", "info", "style"
    line: int | None = None
    column: int | None = None
    message: str
    code: str | None = None
    file_path: str = ""
