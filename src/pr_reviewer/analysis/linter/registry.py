"""Linter tool registry — Language → ToolDef mapping."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pr_reviewer.analysis.language_detector import Language
from pr_reviewer.analysis.linter.models import LinterFinding


@dataclass
class ToolDef:
    name: str
    languages: list[Language]
    install_hint: str
    build_command: Callable[[str], Sequence[str]]  # file_path -> CLI args
    parse_output: Callable[[str, str], list[LinterFinding]]  # stdout, file_path -> findings
    config_file_patterns: list[str] = field(default_factory=list)


class ToolRegistry:
    """Holds the mapping of Language → list[ToolDef]."""

    def __init__(self, tools: dict[Language, list[ToolDef]] | None = None):
        self._tools: dict[Language, list[ToolDef]] = tools or {}

    def register(self, tool: ToolDef) -> None:
        for lang in tool.languages:
            self._tools.setdefault(lang, []).append(tool)

    def get_tools(self, language: Language) -> list[ToolDef]:
        return self._tools.get(language, [])

    def get_available(self, language: Language) -> list[ToolDef]:
        return [t for t in self.get_tools(language) if self._is_installed(t)]

    @staticmethod
    def _is_installed(tool: ToolDef) -> bool:
        cmd = tool.build_command("test.py")[0]
        return shutil.which(cmd) is not None

    @classmethod
    def default(cls) -> ToolRegistry:
        return cls({
            Language.PYTHON: [
                ToolDef(
                    name="pylint",
                    languages=[Language.PYTHON],
                    install_hint="pip install pylint",
                    build_command=lambda f: ["pylint", "--output-format=json", f],
                    parse_output=parse_pylint,
                    config_file_patterns=[".pylintrc", "pyproject.toml"],
                ),
                ToolDef(
                    name="mypy",
                    languages=[Language.PYTHON],
                    install_hint="pip install mypy",
                    build_command=lambda f: ["mypy", "--no-error-summary", f],
                    parse_output=parse_mypy,
                    config_file_patterns=["mypy.ini", "pyproject.toml"],
                ),
                ToolDef(
                    name="bandit",
                    languages=[Language.PYTHON],
                    install_hint="pip install bandit",
                    build_command=lambda f: ["bandit", "-f", "json", "-q", f],
                    parse_output=parse_bandit,
                    config_file_patterns=[".bandit", "pyproject.toml"],
                ),
            ],
            Language.JAVASCRIPT: [
                ToolDef(
                    name="eslint",
                    languages=[Language.JAVASCRIPT, Language.TYPESCRIPT],
                    install_hint="npm install -g eslint",
                    build_command=lambda f: ["eslint", "-f", "json", f],
                    parse_output=parse_eslint,
                    config_file_patterns=[".eslintrc.js", ".eslintrc.json", "eslint.config.js"],
                ),
            ],
            Language.GO: [
                ToolDef(
                    name="go vet",
                    languages=[Language.GO],
                    install_hint="go tool vet (built-in)",
                    build_command=lambda f: ["go", "vet", str(Path(f).parent)],
                    parse_output=parse_govet,
                    config_file_patterns=["go.mod"],
                ),
            ],
            Language.RUST: [
                ToolDef(
                    name="clippy",
                    languages=[Language.RUST],
                    install_hint="rustup component add clippy",
                    build_command=lambda f: ["cargo", "clippy", "--message-format=json"],
                    parse_output=parse_clippy,
                    config_file_patterns=["Cargo.toml"],
                ),
            ],
            Language.SHELL: [
                ToolDef(
                    name="shellcheck",
                    languages=[Language.SHELL],
                    install_hint="apt install shellcheck",
                    build_command=lambda f: ["shellcheck", "-f", "json", f],
                    parse_output=parse_shellcheck,
                    config_file_patterns=[],
                ),
            ],
        })


# ── Parsers ────────────────────────────────────────────

import json
from pathlib import Path


def parse_pylint(stdout: str, file_path: str) -> list[LinterFinding]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    findings: list[LinterFinding] = []
    for item in data:
        findings.append(LinterFinding(
            tool="pylint",
            severity=_pylint_severity(item.get("type", "info")),
            line=item.get("line"),
            column=item.get("column"),
            message=item.get("message", ""),
            code=item.get("message-id", ""),
            file_path=item.get("path", file_path),
        ))
    return findings


def _pylint_severity(msg_type: str) -> str:
    return {
        "fatal": "error",
        "error": "error",
        "warning": "warning",
        "convention": "info",
        "refactor": "info",
    }.get(msg_type, "warning")


def parse_mypy(stdout: str, file_path: str) -> list[LinterFinding]:
    findings: list[LinterFinding] = []
    for line in stdout.strip().split("\n"):
        # Format: "file:line:col: severity: message  [code]"
        parts = line.split(":", 4)
        if len(parts) < 4:
            continue
        try:
            findings.append(LinterFinding(
                tool="mypy",
                severity="error",
                line=int(parts[1]) if parts[1].strip().isdigit() else None,
                column=int(parts[2]) if parts[2].strip().isdigit() else None,
                message=parts[3].strip() if len(parts) > 3 else line,
                code=None,
                file_path=parts[0] if parts[0] else file_path,
            ))
        except (ValueError, IndexError):
            continue
    return findings


def parse_bandit(stdout: str, file_path: str) -> list[LinterFinding]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    findings: list[LinterFinding] = []
    for item in data.get("results", []):
        findings.append(LinterFinding(
            tool="bandit",
            severity=_bandit_severity(item.get("issue_severity", "")),
            line=item.get("line_number"),
            message=f"{item.get('test_name', '')}: {item.get('issue_text', '')}",
            code=item.get("test_id", ""),
            file_path=item.get("filename", file_path),
        ))
    return findings


def _bandit_severity(sev: str) -> str:
    return {"HIGH": "error", "MEDIUM": "warning", "LOW": "info"}.get(sev, "info")


def parse_eslint(stdout: str, file_path: str) -> list[LinterFinding]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    findings: list[LinterFinding] = []
    for item in data:
        for msg in item.get("messages", []):
            findings.append(LinterFinding(
                tool="eslint",
                severity="error" if msg.get("severity") == 2 else "warning",
                line=msg.get("line"),
                column=msg.get("column"),
                message=msg.get("message", ""),
                code=msg.get("ruleId", ""),
                file_path=item.get("filePath", file_path),
            ))
    return findings


def parse_govet(stdout: str, file_path: str) -> list[LinterFinding]:
    findings: list[LinterFinding] = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        findings.append(LinterFinding(
            tool="go vet",
            severity="error",
            message=line,
            file_path=file_path,
        ))
    return findings


def parse_clippy(stdout: str, file_path: str) -> list[LinterFinding]:
    findings: list[LinterFinding] = []
    for line in stdout.strip().split("\n"):
        try:
            data = json.loads(line)
            msg = data.get("message", {})
            spans = msg.get("spans", [])
            if msg.get("level") in ("error", "warning"):
                findings.append(LinterFinding(
                    tool="clippy",
                    severity=msg.get("level", "warning"),
                    line=spans[0].get("line_start") if spans else None,
                    column=spans[0].get("column_start") if spans else None,
                    message=msg.get("rendered", msg.get("message", "")),
                    code=msg.get("code"),
                ))
        except json.JSONDecodeError:
            continue
    return findings


def parse_shellcheck(stdout: str, file_path: str) -> list[LinterFinding]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    findings: list[LinterFinding] = []
    for item in data:
        findings.append(LinterFinding(
            tool="shellcheck",
            severity="warning" if item.get("level") == "warning" else "error",
            line=item.get("line"),
            column=item.get("column"),
            message=item.get("message", ""),
            code=f"SC{item.get('code')}",
            file_path=item.get("file", file_path),
        ))
    return findings
