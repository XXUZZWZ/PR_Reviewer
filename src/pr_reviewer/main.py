"""CLI entry point for pr-review — full pipeline orchestration."""

from __future__ import annotations

import json
import logging
import tomllib
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
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


# ── Config subcommands ───────────────────────────────────────────

config_app = typer.Typer(help="Manage configuration", no_args_is_help=True)
app.add_typer(config_app, name="config")

DEFAULT_CONFIG_PATH = Path("config.toml")


@config_app.command()
def init(
    path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--path", "-p", help="Config file path"),
) -> None:
    """Interactively create a config.toml."""
    if path.exists():
        overwrite = typer.confirm(f"{path} already exists. Overwrite?")
        if not overwrite:
            console.print("[dim]Aborted.[/]")
            return

    console.print("[bold]PR Reviewer — Configuration Setup[/]\n")

    gh_token = typer.prompt("GitHub personal access token", default="", hide_input=True)
    gh_url = typer.prompt("GitHub API URL (Enterprise only)", default="https://api.github.com")

    console.print()
    llm_key = typer.prompt("LLM API key", default="", hide_input=True)
    llm_model = typer.prompt("Default model", default="deepseek-v4-pro")
    llm_url = typer.prompt("LLM base URL (Anthropic-compatible)", default="https://api.deepseek.com/anthropic")

    console.print()
    dep_depth = typer.prompt("Max dependency depth", default=2, type=int)
    include_tests = typer.confirm("Include test files in review?", default=True)
    linter_timeout = typer.prompt("Linter timeout (seconds)", default=60, type=int)

    content = f"""[github]
token = "{gh_token}"
base_url = "{gh_url}"

[llm]
provider = "deepseek"
model = "{llm_model}"
api_key = "{llm_key}"
base_url = "{llm_url}"
max_output_tokens = 8192
temperature = 0.3

[analysis]
max_dependency_depth = {dep_depth}
include_test_files = {"true" if include_tests else "false"}

[linters]
enabled = true
timeout_seconds = {linter_timeout}

[report]
terminal_verbosity = "default"
save_path = ""
"""
    path.write_text(content)
    console.print(f"\n[bold green]Config saved to {path.absolute()}[/]")


@config_app.command()
def show(
    path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Config file path"),
) -> None:
    """Show current effective configuration."""
    settings = Settings.load(path)

    table = Table(title="Current Configuration", show_header=False, border_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_section()
    table.add_row("[bold]github.token[/]", _mask(settings.github.token))
    table.add_row("[bold]github.base_url[/]", settings.github.base_url)
    table.add_section()
    table.add_row("[bold]llm.provider[/]", settings.llm.provider)
    table.add_row("[bold]llm.model[/]", settings.llm.model)
    table.add_row("[bold]llm.api_key[/]", _mask(settings.llm.api_key))
    table.add_row("[bold]llm.base_url[/]", settings.llm.base_url)
    table.add_row("[bold]llm.max_output_tokens[/]", str(settings.llm.max_output_tokens))
    table.add_row("[bold]llm.temperature[/]", str(settings.llm.temperature))
    table.add_section()
    table.add_row("[bold]analysis.max_dependency_depth[/]", str(settings.analysis.max_dependency_depth))
    table.add_row("[bold]analysis.include_test_files[/]", str(settings.analysis.include_test_files))
    table.add_section()
    table.add_row("[bold]linters.enabled[/]", str(settings.linters.enabled))
    table.add_row("[bold]linters.timeout_seconds[/]", str(settings.linters.timeout_seconds))
    table.add_section()
    table.add_row("[bold]report.terminal_verbosity[/]", settings.report.terminal_verbosity)
    table.add_row("[bold]report.save_path[/]", settings.report.save_path or "(auto: reports/)")
    table.add_section()
    table.add_row("Config file", str(path.absolute()) if path.exists() else "(not found — using defaults + env)")

    console.print(table)


@config_app.command()
def set(
    key: str = typer.Argument(help="Config key, e.g. llm.model"),
    value: str = typer.Argument(help="New value"),
    path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--path", "-p", help="Config file path"),
) -> None:
    """Set a value in config.toml (creates file if missing)."""
    if not path.exists():
        console.print(f"[yellow]{path} not found. Run 'pr-review config init' first.[/]")
        raise typer.Exit(1)

    try:
        section, key_name = key.split(".", 1)
    except ValueError:
        console.print(f"[red]Invalid key '{key}'. Use format: section.key (e.g. llm.model)[/]")
        raise typer.Exit(1)

    with open(path, "rb") as f:
        data = tomllib.load(f)

    if section not in data:
        data[section] = {}
    data[section][key_name] = value

    # Simple TOML write — preserves comments for well-known sections
    _write_toml(path, data)
    console.print(f"[bold green]{key} = {value}[/]")


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "****" + s[-4:]


def _write_toml(path: Path, data: dict) -> None:
    """Write config dict as TOML, preserving structure."""
    lines: list[str] = []
    for section in ("github", "llm", "analysis", "linters", "report"):
        if section in data:
            lines.append(f"[{section}]")
            for k, v in data[section].items():
                if isinstance(v, bool):
                    lines.append(f"{k} = {'true' if v else 'false'}")
                elif isinstance(v, (int, float)):
                    lines.append(f"{k} = {v}")
                else:
                    lines.append(f'{k} = "{v}"')
            lines.append("")
    path.write_text("\n".join(lines))


@app.command()
def version() -> None:
    """Show version."""
    console.print("pr-review v0.1.0")
