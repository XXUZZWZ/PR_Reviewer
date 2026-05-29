"""Report data models."""

from __future__ import annotations

from pydantic import BaseModel, Field
from datetime import datetime


class FileLocation(BaseModel):
    line_start: int | None = None
    line_end: int | None = None


class Finding(BaseModel):
    severity: str
    category: str
    location: FileLocation = Field(default_factory=FileLocation)
    title: str = ""
    description: str = ""
    suggestion: str = ""
    confidence: float = 0.0
    linter_corroboration: str | None = None


class FileAnalysis(BaseModel):
    file_path: str
    summary: str = ""
    findings: list[Finding] = []
    dependencies_impact: str = ""
    linter_correlation: str = ""


class OverallAssessment(BaseModel):
    verdict: str = ""  # "approved", "changes_requested", "comments"
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0


class Report(BaseModel):
    pr_info: dict = {}
    overall: OverallAssessment = Field(default_factory=OverallAssessment)
    files: list[FileAnalysis] = []
    cross_cutting: list[Finding] = []
    generated_at: str = ""
    model_used: str = ""
    total_tokens_used: int = 0
