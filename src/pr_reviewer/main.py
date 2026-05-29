"""CLI entry point for pr-review — full pipeline orchestration."""

from __future__ import annotations

import logging
import json
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
    output: Path | None = typer.Option(None, "--output", "-o", help="Save report to file"),
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
            raw_response = llm.analyze_file(SYSTEM_PROMPT, pr_context, file_context)

            if raw_response:
                parsed = parse_file_analysis(raw_response)
                if parsed:
                    findings = [
                        Finding(
                            severity=f.get("severity", "info"),
                            category=f.get("category", "code_smell"),
                            location=FileLocation(
                                line_start=f.get("location", {}).get("line_start"),
                                line_end=f.get("location", {}).get("line_end"),
                            ),
                            title=f.get("title", ""),
                            description=f.get("description", ""),
                            suggestion=f.get("suggestion", ""),
                            confidence=f.get("confidence", 0.0),
                        )
                        for f in parsed.get("findings", [])
                    ]
                    file_analyses.append(FileAnalysis(
                        file_path=cf.path,
                        summary=parsed.get("summary", ""),
                        findings=findings,
                        dependencies_impact=parsed.get("dependencies_impact", ""),
                        linter_correlation=parsed.get("linter_correlation", ""),
                    ))
                else:
                    console.print(f"  [yellow]Failed to parse LLM response for {cf.path}[/]")
                    file_analyses.append(FileAnalysis(file_path=cf.path))
            else:
                console.print(f"  [red]LLM call failed for {cf.path}[/]")
                file_analyses.append(FileAnalysis(file_path=cf.path))

            progress.update(task, advance=1)

    # ── Step 6: Build and render report ──
    report = build_report(pr_info, file_analyses, settings.llm.model, total_tokens)
    format_report(report)

    # ── Step 7: Save if requested ──
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))
        console.print(f"\n[dim]Report saved to {output}[/]")

    if settings.report.save_path:
        save_path = Path(settings.report.save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))


@app.command()
def version() -> None:
    """Show version."""
    console.print("pr-review v0.1.0")
