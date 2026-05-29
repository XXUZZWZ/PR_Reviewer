"""Execute linter CLI tools via subprocess."""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path

from pr_reviewer.analysis.linter.models import LinterFinding
from pr_reviewer.analysis.linter.registry import ToolDef

logger = logging.getLogger(__name__)


def run_linter(tool: ToolDef, file_path: str, repo_dir: Path, timeout: int = 60) -> list[LinterFinding]:
    """Run a single linter on a file. Returns findings or empty list on failure."""
    abs_path = repo_dir / file_path
    if not abs_path.exists():
        logger.warning("File not found for linter: %s", abs_path)
        return []

    cmd = list(tool.build_command(str(abs_path)))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(repo_dir),
        )
    except subprocess.TimeoutExpired:
        logger.warning("%s timed out on %s (%ds)", tool.name, file_path, timeout)
        return []
    except FileNotFoundError:
        logger.warning("%s not installed", tool.name)
        return []
    except Exception as exc:
        logger.warning("%s failed on %s: %s", tool.name, file_path, exc)
        return []

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    # Some tools write findings to stderr (mypy, go vet)
    if not stdout and stderr:
        stdout = stderr

    try:
        return tool.parse_output(stdout, file_path)
    except Exception as exc:
        logger.warning("%s output parse failed on %s: %s", tool.name, file_path, exc)
        return []


def run_linters_for_file(
    tools: list[ToolDef],
    file_path: str,
    repo_dir: Path,
    timeout: int = 60,
) -> list[LinterFinding]:
    """Run all applicable linters on a file. Degrades gracefully per-tool."""
    all_findings: list[LinterFinding] = []
    for tool in tools:
        findings = run_linter(tool, file_path, repo_dir, timeout)
        all_findings.extend(findings)
        if findings:
            logger.info("  %s: %d findings", tool.name, len(findings))
        else:
            logger.info("  %s: no findings", tool.name)
    return all_findings
