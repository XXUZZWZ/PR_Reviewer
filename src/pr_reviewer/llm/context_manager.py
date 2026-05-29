"""Token-aware context management and prioritization."""

from __future__ import annotations

from pr_reviewer.analysis.linter.models import LinterFinding


class TokenBudget:
    """Token budget allocation across context sections."""

    SYSTEM_PROMPT: int = 2000
    PR_CONTEXT: int = 2000
    FILE_CONTENT: int = 4000
    DIFF: int = 8000
    DEPENDENCY_CONTEXT: int = 6000
    LINTER_OUTPUT: int = 4000

    TOTAL_TARGET: int = 30000


def estimate_tokens(text: str) -> int:
    """Rough token count: ~4 chars per token for code."""
    return len(text) // 4


def prioritize_findings(
    findings: list[LinterFinding],
    max_items: int = 30,
) -> list[LinterFinding]:
    """Prioritize linter findings: errors/warnings first, then info/style."""
    severity_order = {"error": 0, "warning": 1, "info": 2, "style": 3}
    sorted_findings = sorted(findings, key=lambda f: severity_order.get(f.severity, 4))
    return sorted_findings[:max_items]
