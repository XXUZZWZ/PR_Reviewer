"""Rich terminal output formatting."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

from pr_reviewer.report.models import Report, Finding

console = Console()

SEVERITY_COLORS = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "dim",
    "info": "blue",
}

SEVERITY_ICON = {
    "critical": "[bold red]CRIT[/]",
    "high": "[red]HIGH[/]",
    "medium": "[yellow]MED [/]",
    "low": "[dim]LOW [/]",
    "info": "[blue]INFO[/]",
}


def format_report(report: Report) -> None:
    """Render the full report to the terminal."""
    _print_header(report)
    _print_overall(report)
    _print_cross_cutting(report)
    _print_file_analyses(report)
    _print_footer(report)


def _print_header(report: Report) -> None:
    pr = report.pr_info
    stats = pr.get("stats", {})
    text = Text()
    text.append(f"PR #{pr.get('pr_number')}: {pr.get('title')}", style="bold")
    text.append(f"\n{pr.get('owner')}/{pr.get('repo')}  "
                f"base: {pr.get('base_branch')} ← head: {pr.get('head_branch')}")
    text.append(f"\n+{stats.get('total_additions', 0)} "
                f"-{stats.get('total_deletions', 0)} "
                f"across {stats.get('total_files', 0)} files")
    text.append(f"\nModel: {report.model_used}  "
                f"Tokens: {report.total_tokens_used:,}")
    console.print(Panel(text, title="PR Review", border_style="bold"))


def _print_overall(report: Report) -> None:
    o = report.overall
    color = "red" if o.critical_count > 0 else "yellow" if o.high_count > 0 else "green"
    console.print(f"\n[bold]Overall:[/] [{color}]{o.verdict}[/]")
    counts = (
        f"Critical: {o.critical_count} | High: {o.high_count} | "
        f"Medium: {o.medium_count} | Low: {o.low_count} | Info: {o.info_count}"
    )
    console.print(f"[dim]{counts}[/]")


def _print_cross_cutting(report: Report) -> None:
    if not report.cross_cutting:
        return
    console.print("\n[bold]Cross-cutting Concerns:[/]")
    for f in report.cross_cutting:
        console.print(f"  {SEVERITY_ICON.get(f.severity, f.severity)} {f.title}")


def _print_file_analyses(report: Report) -> None:
    for fa in report.files:
        if not fa.findings:
            continue
        console.print(f"\n[bold cyan]{fa.file_path}[/]")
        if fa.summary:
            console.print(f"  [dim]{fa.summary[:200]}[/]")

        table = Table(show_header=False, padding=(0, 1), box=None)
        table.add_column("sev", width=5)
        table.add_column("category", width=14)
        table.add_column("title")
        table.add_column("conf", width=6, justify="right")

        for f in fa.findings:
            table.add_row(
                SEVERITY_ICON.get(f.severity, f.severity),
                f"[dim]{f.category}[/]",
                f.title,
                f"[dim]{f.confidence:.0%}[/]",
            )
            if f.description:
                table.add_row("", "", f"[dim]{f.description[:120]}[/]", "")
            if f.suggestion:
                table.add_row("", "", f"[green]Fix: {f.suggestion[:120]}[/]", "")

        console.print(table)


def _print_footer(report: Report) -> None:
    if report.generated_at:
        console.print(f"\n[dim]Generated: {report.generated_at}[/]")


def format_findings_plain(report: Report) -> str:
    """Return a plain text summary string."""
    lines: list[str] = []
    for fa in report.files:
        for f in fa.findings:
            lines.append(
                f"[{f.severity}] {fa.file_path}:{f.location.line_start or '?'} "
                f"{f.title} — {f.suggestion}"
            )
    return "\n".join(lines)
