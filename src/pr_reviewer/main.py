"""CLI entry point for pr-review."""

from __future__ import annotations

import typer
from pathlib import Path
from rich.console import Console

from pr_reviewer.config.settings import Settings

app = typer.Typer(
    name="pr-review",
    help="AI-powered PR code review assistant",
    no_args_is_help=True,
)
console = Console()


@app.command()
def review(
    pr_url: str = typer.Argument(help="GitHub PR URL, e.g. https://github.com/owner/repo/pull/123"),
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to TOML config file"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Save report to file"),
    model: str | None = typer.Option(None, "--model", "-m", help="Override LLM model"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Review a GitHub Pull Request."""
    settings = Settings.load(config)

    if model:
        settings.llm.model = model

    console.print(f"[bold]PR Review[/] — {pr_url}")
    console.print(f"Model: {settings.llm.model} | Provider: {settings.llm.provider}")

    # TODO: full pipeline — fetch PR, analyze, report
    console.print("[yellow]Pipeline not yet implemented.[/]")


@app.command()
def version() -> None:
    """Show version."""
    console.print("pr-review v0.1.0")
