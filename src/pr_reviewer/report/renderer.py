"""Render reports to HTML and Markdown via Jinja2 templates.

Constructs GitHub/GitLab permalinks for inline code references.
"""

from __future__ import annotations

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from pr_reviewer.report.models import Report

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _make_source_url(owner: str, repo: str, head_sha: str, platform: str = "github"):
    """Return a closure that generates source URLs for a specific PR."""

    if platform == "gitlab":
        base = f"https://gitlab.com/{owner}/{repo}/-/blob/{head_sha}"
    else:
        base = f"https://github.com/{owner}/{repo}/blob/{head_sha}"

    def source_url(file_path: str, line: int = 1) -> str:
        return f"{base}/{file_path}#L{line}"

    return source_url


def render_html(report: Report, platform: str = "github") -> str:
    """Render the report as a standalone HTML file."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.j2")

    pr = report.pr_info
    source_url = _make_source_url(
        pr.get("owner", ""),
        pr.get("repo", ""),
        pr.get("head_sha", "main"),
        platform,
    )

    return template.render(report=report, source_url=source_url)


def render_markdown(report: Report, platform: str = "github") -> str:
    """Render the report as a Markdown file."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
    )
    template = env.get_template("report.md.j2")

    pr = report.pr_info
    source_url = _make_source_url(
        pr.get("owner", ""),
        pr.get("repo", ""),
        pr.get("head_sha", "main"),
        platform,
    )

    return template.render(report=report, source_url=source_url)


def detect_platform(pr_url: str) -> str:
    """Detect if the PR URL is GitHub or GitLab."""
    if "gitlab" in pr_url.lower():
        return "gitlab"
    return "github"
