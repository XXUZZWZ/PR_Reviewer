"""Aggregate per-file analyses into a unified PR report."""

from __future__ import annotations

from pr_reviewer.github.models import PRInfo
from pr_reviewer.report.models import (
    Report,
    FileAnalysis,
    Finding,
    FileLocation,
    OverallAssessment,
)
from datetime import datetime


def build_report(
    pr_info: PRInfo,
    file_analyses: list[FileAnalysis],
    model_name: str,
    total_tokens: int = 0,
) -> Report:
    """Aggregate per-file findings into a PR-level report with cross-cutting analysis."""

    all_findings: list[tuple[str, Finding]] = []
    for fa in file_analyses:
        for f in fa.findings:
            all_findings.append((fa.file_path, f))

    # Severity counts
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for _, f in all_findings:
        if f.severity in sev_counts:
            sev_counts[f.severity] += 1

    # Determine overall verdict
    if sev_counts["critical"] > 0:
        verdict = "Changes requested (critical issues)"
    elif sev_counts["high"] > 3:
        verdict = "Changes requested"
    elif sev_counts["high"] > 0 or sev_counts["medium"] > 5:
        verdict = "Comments (address suggestions before merge)"
    else:
        verdict = "Approved (minor suggestions only)"

    # Cross-cutting: find patterns across files
    cross_cutting = _detect_cross_cutting(all_findings)

    return Report(
        pr_info={
            "title": pr_info.title,
            "owner": pr_info.owner,
            "repo": pr_info.repo,
            "pr_number": pr_info.pr_number,
            "base_branch": pr_info.base_branch,
            "head_branch": pr_info.head_branch,
            "stats": pr_info.stats.model_dump(),
        },
        overall=OverallAssessment(
            verdict=verdict,
            critical_count=sev_counts["critical"],
            high_count=sev_counts["high"],
            medium_count=sev_counts["medium"],
            low_count=sev_counts["low"],
            info_count=sev_counts["info"],
        ),
        files=file_analyses,
        cross_cutting=cross_cutting,
        generated_at=datetime.now().isoformat(),
        model_used=model_name,
        total_tokens_used=total_tokens,
    )


def _detect_cross_cutting(
    all_findings: list[tuple[str, Finding]],
) -> list[Finding]:
    """Detect patterns that repeat across multiple files."""
    from collections import Counter

    cross_cutting: list[Finding] = []

    # Group by category
    cat_counter = Counter(f.category for _, f in all_findings)
    cat_files: dict[str, set[str]] = {}
    for file_path, f in all_findings:
        cat_files.setdefault(f.category, set()).add(file_path)

    for category, count in cat_counter.most_common(5):
        files = cat_files.get(category, set())
        if len(files) >= 2:
            cross_cutting.append(Finding(
                severity="medium",
                category=category,
                title=f"{count} {category} issues across {len(files)} files",
                description=f"The category '{category}' appears in {len(files)} files. Review if there is a systemic pattern.",
                confidence=0.6,
            ))

    return cross_cutting
