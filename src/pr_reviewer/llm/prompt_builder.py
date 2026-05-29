"""Build LLM prompts from PR data, dependency context, and linter results."""

from __future__ import annotations

from pr_reviewer.analysis.dependency_graph import DependencyContext
from pr_reviewer.analysis.linter.models import LinterFinding
from pr_reviewer.github.models import PRInfo, ChangedFile

SYSTEM_PROMPT = """You are an expert code reviewer. Analyze the changed file in context of the PR.

## Review Guidelines

1. **Security**: Look for injection vulnerabilities, exposed secrets, missing auth checks, unsafe deserialization.
2. **Performance**: Identify N+1 queries, unnecessary allocations, blocking I/O, missing caching.
3. **Logic errors**: Off-by-one, null/undefined handling, race conditions, incorrect error handling.
4. **API misuse**: Incorrect library/framework usage, deprecated calls, wrong parameter types.
5. **Code quality**: Dead code, over-complexity, unclear naming, missing tests.

For each finding, provide:
- severity: "critical" | "high" | "medium" | "low" | "info"
- category: "security" | "performance" | "logic_error" | "code_smell" | "api_misuse" | "testing" | "maintainability"
- location: file path and line range
- title: short description
- description: detailed explanation of the issue
- suggestion: concrete, actionable fix
- confidence: 0.0 to 1.0

## Linter Results

Automated linter findings are included below. Use them as:
- **Corroboration**: If the linter flags something you see, raise confidence and reference the linter rule.
- **Explanation**: Explain WHY the linter flagged it, not just WHAT.
- **New issues**: Flag problems the linter missed (e.g., design issues, semantic errors).

## Dependency Context

The file's dependencies and dependents are provided. Check:
- Are new imports used correctly?
- Does the change break any dependent code?
- Are error types and return values consistent with callers' expectations?

## Output Format

Return ONLY a JSON object (no markdown fences, no other text):

{
  "summary": "One paragraph describing the change",
  "findings": [
    {
      "severity": "high",
      "category": "logic_error",
      "location": {"line_start": 53, "line_end": 57},
      "title": "...",
      "description": "...",
      "suggestion": "...",
      "confidence": 0.92
    }
  ],
  "dependencies_impact": "How this change affects dependencies/dependents",
  "linter_correlation": "Explain which linter findings you agree/disagree with and why"
}"""


def build_pr_context(pr: PRInfo) -> str:
    """Build the PR overview section (cached across file calls)."""
    files_summary = "\n".join(
        f"  [{f.status}] {f.path} (+{f.additions}/-{f.deletions})"
        for f in pr.changed_files[:20]
    )
    return f"""## PR OVERVIEW

PR #{pr.pr_number}: {pr.title}
Repository: {pr.owner}/{pr.repo}
Base: {pr.base_branch} ← Head: {pr.head_branch}
Description: {pr.description[:500]}
Stats: +{pr.stats.total_additions}/-{pr.stats.total_deletions} across {pr.stats.total_files} files

Changed files:
{files_summary}"""


def build_file_context(
    changed_file: ChangedFile,
    dependency_context: DependencyContext,
    linter_findings: list[LinterFinding],
    file_content: str | None,
) -> str:
    """Build the per-file analysis section."""

    sections: list[str] = [
        f"## FILE ANALYSIS",
        f"",
        f"**File:** {changed_file.path}",
        f"**Status:** {changed_file.status} (+{changed_file.additions}/-{changed_file.deletions})",
        f"**Language:** {dependency_context.language.value}",
    ]

    # File content / structure overview
    if file_content:
        truncated = file_content[:4000]
        if len(file_content) > 4000:
            truncated += "\n... (truncated)"
        sections.append(f"\n### File Content\n```\n{truncated}\n```")

    # Diff
    if changed_file.diff:
        diff_text = changed_file.diff[:8000]
        sections.append(f"\n### Diff\n```diff\n{diff_text}\n```")

    # Dependency context
    deps_section = "\n### Dependencies (files this file uses)\n"
    if dependency_context.dependencies:
        for dep_path, snippet in list(dependency_context.dependencies.items())[:10]:
            deps_section += f"\n**{dep_path}:**\n```\n{snippet[:500]}\n```\n"
    else:
        deps_section += "No project-internal dependencies detected.\n"

    deps_section += "\n### Dependents (files that use this file)\n"
    if dependency_context.dependents:
        for dep_path, snippet in list(dependency_context.dependents.items())[:10]:
            deps_section += f"\n**{dep_path}:**\n```\n{snippet[:500]}\n```\n"
    else:
        deps_section += "No project-internal dependents detected.\n"
    sections.append(deps_section)

    # Linter results
    linter_section = "\n### Linter Results\n"
    if linter_findings:
        for lf in linter_findings[:30]:
            linter_section += (
                f"- [{lf.severity.upper()}] `{lf.tool}` "
                f"{lf.code or ''}: {lf.message}"
            )
            if lf.line:
                linter_section += f" (line {lf.line})"
            linter_section += "\n"
    else:
        linter_section += "No linter issues detected (positive signal — focus on design/logic).\n"
    sections.append(linter_section)

    return "\n".join(sections)
