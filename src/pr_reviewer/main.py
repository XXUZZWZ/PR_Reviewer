"""CLI entry point for pr-review — full pipeline orchestration."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from pr_reviewer.config.settings import Settings
from pr_reviewer.github.client import GitHubClient, parse_pr_url
from pr_reviewer.analysis.language_detector import detect_language, Language
from pr_reviewer.analysis.dependency_graph import DependencyGraph
from pr_reviewer.analysis.linter.registry import ToolRegistry
from pr_reviewer.analysis.linter.runner import run_linters_for_file
from pr_reviewer.analysis.linter.models import LinterFinding
from pr_reviewer.llm.client import LLMClient
from pr_reviewer.llm.prompt_builder import (
    SYSTEM_PROMPT,
    build_pr_context,
    build_file_context,
)
from pr_reviewer.llm.response_parser import parse_file_analysis
from pr_reviewer.report.models import Report, FileAnalysis, Finding, FileLocation
from pr_reviewer.report.generator import build_report
from pr_reviewer.report.formatter import format_report
from pr_reviewer.report.renderer import render_html, render_markdown, detect_platform
from pr_reviewer.llm.translator import translate_file_analysis
from pr_reviewer.utils.git import ensure_repo_cloned, get_file_content

app = typer.Typer(
    name="pr-review",
    help="AI-powered PR code review assistant",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


@app.command()
def review(
    pr_url: str = typer.Argument(help="GitHub PR URL, e.g. https://github.com/owner/repo/pull/123"),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to TOML config file"),
    output_dir: Path | None = typer.Option(None, "--output", "-o", help="Output directory for reports"),
    fmt: str = typer.Option("all", "--format", "-f", help="Report format: json, md, html, all"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override LLM model"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    skip_linters: bool = typer.Option(False, "--skip-linters", help="Skip linter checks"),
) -> None:
    """Review a GitHub Pull Request."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    settings = Settings.load(config)
    if model:
        settings.llm.model = model

    console.print(f"[bold]PR Review[/] — {pr_url}")
    console.print(f"Model: {settings.llm.model} | Provider: {settings.llm.provider}")

    # ── Step 1: Parse PR URL ──
    owner, repo, pr_num = parse_pr_url(pr_url)
    platform = detect_platform(pr_url)
    console.print(f"Fetching PR #{pr_num} from {owner}/{repo}...")

    # ── Step 2: Fetch PR metadata ──
    gh = GitHubClient(settings.github)
    pr_info = gh.fetch_pr(owner, repo, pr_num)
    console.print(
        f"PR: {pr_info.title} | "
        f"+{pr_info.stats.total_additions}/-{pr_info.stats.total_deletions} "
        f"in {pr_info.stats.total_files} files"
    )

    # Filter to reviewable files
    changed_files = [
        f for f in pr_info.changed_files
        if f.status != "removed" and detect_language(f.path) != Language.UNKNOWN
    ]
    if not changed_files:
        console.print("[yellow]No reviewable files in this PR.[/]")
        return

    console.print(f"Reviewing {len(changed_files)} files...")

    # ── Step 3: Clone repo ──
    repo_dir = ensure_repo_cloned(owner, repo, pr_info.head_sha, pr_info.base_sha)

    # ── Step 4: Build dependency graph ──
    changed_paths = {f.path for f in changed_files}
    dep_graph = DependencyGraph(repo_dir)
    dep_graph.build(changed_paths)
    console.print(f"Dependency graph: {len(dep_graph.nodes)} nodes")

    # ── Step 5: Per-file analysis loop ──
    tool_registry = ToolRegistry.default() if not skip_linters else None
    llm = LLMClient(settings.llm)
    pr_context = build_pr_context(pr_info)

    file_analyses: list[FileAnalysis] = []
    total_tokens = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing...", total=len(changed_files))

        for cf in changed_files:
            progress.update(task, description=f"Analyzing {cf.path}...")

            lang = detect_language(cf.path)
            dep_context = dep_graph.get_context(cf.path, lang)

            # Run linters
            linter_findings: list[LinterFinding] = []
            if tool_registry and settings.linters.enabled:
                tools = tool_registry.get_available(lang)
                if tools:
                    linter_findings = run_linters_for_file(
                        tools, cf.path, repo_dir, settings.linters.timeout_seconds
                    )

            # Get file content for context
            file_content = get_file_content(repo_dir, cf.path)

            # Build prompt and call LLM
            file_context = build_file_context(cf, dep_context, linter_findings, file_content)
            result = llm.analyze_file(SYSTEM_PROMPT, pr_context, file_context)

            if result:
                raw_response, inp_tok, out_tok = result
                total_tokens += inp_tok + out_tok
                parsed = parse_file_analysis(raw_response)
                if parsed:
                    findings = []
                    for f in parsed.get("findings", []):
                        loc = FileLocation(
                            line_start=f.get("location", {}).get("line_start"),
                            line_end=f.get("location", {}).get("line_end"),
                        )
                        snippet = _extract_code_snippet(cf.diff, file_content, loc)
                        findings.append(Finding(
                            severity=f.get("severity", "info"),
                            category=f.get("category", "code_smell"),
                            location=loc,
                            title=f.get("title", ""),
                            description=f.get("description", ""),
                            suggestion=f.get("suggestion", ""),
                            confidence=f.get("confidence", 0.0),
                            code_snippet=snippet,
                        ))
                    fa = FileAnalysis(
                        file_path=cf.path,
                        summary=parsed.get("summary", ""),
                        diff=cf.diff,
                        additions=cf.additions,
                        deletions=cf.deletions,
                        findings=findings,
                        dependencies_impact=parsed.get("dependencies_impact", ""),
                        linter_correlation=parsed.get("linter_correlation", ""),
                    )
                    # Translate to Chinese
                    tr_tok = translate_file_analysis(fa, settings.llm)
                    total_tokens += tr_tok
                    file_analyses.append(fa)
                else:
                    console.print(f"  [yellow]Failed to parse LLM response for {cf.path}[/]")
                    file_analyses.append(FileAnalysis(file_path=cf.path, diff=cf.diff, additions=cf.additions, deletions=cf.deletions))
            else:
                console.print(f"  [red]LLM call failed for {cf.path}[/]")
                file_analyses.append(FileAnalysis(file_path=cf.path, diff=cf.diff, additions=cf.additions, deletions=cf.deletions))

            progress.update(task, advance=1)

    # ── Step 6: Build and render report ──
    report = build_report(pr_info, file_analyses, settings.llm.model, total_tokens)
    # Inject head_sha for URL generation
    report.pr_info["head_sha"] = pr_info.head_sha
    format_report(report)

    # ── Step 7: Save reports ──
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_dir:
        out_path = output_dir
    else:
        out_path = Path("reports") / f"pr_{pr_num}_{date_str}"

    out_path.mkdir(parents=True, exist_ok=True)
    formats = ["json", "md", "html"] if fmt == "all" else [fmt]

    for f in formats:
        if f == "json":
            p = out_path / f"report.json"
            p.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        elif f == "md":
            p = out_path / f"report.md"
            p.write_text(render_markdown(report, platform))
        elif f == "html":
            p = out_path / f"report.html"
            p.write_text(render_html(report, platform))
        console.print(f"[dim]Saved: {p}[/]")

    console.print(f"\n[bold green]Reports saved to {out_path.absolute()}[/]")


def _extract_code_snippet(diff: str, file_content: str | None, loc: FileLocation) -> str:
    """Extract code lines around a finding's location from diff or file content."""
    if not loc.line_start:
        return ""

    # Prefer file content (has full context)
    source = file_content
    if source:
        lines = source.split("\n")
    elif diff:
        # Fall back to diff lines that are context or additions
        diff_lines = [l[1:] for l in diff.split("\n") if l and l[0] in (" ", "+", "-")]
        lines = diff_lines
    else:
        return ""

    start = max(0, loc.line_start - 4)
    end = min(len(lines), (loc.line_end or loc.line_start) + 3)
    snippet_lines = lines[start:end]

    return "\n".join(snippet_lines)


@app.command()
def version() -> None:
    """Show version."""
    console.print("pr-review v0.1.0")
