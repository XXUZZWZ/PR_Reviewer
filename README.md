# PR Reviewer

AI-powered CLI tool for automated GitHub Pull Request code review.

## Features

- **PR Change Summary** — Summarizes code changes to help reviewers quickly understand scope and intent
- **Risk Detection** — Identifies security vulnerabilities, performance issues, logic errors, and code quality problems
- **Review Suggestions** — Generates specific, actionable review comments with severity, category, and confidence scoring
- **Dependency-Aware Analysis** — Analyzes each changed file with its dependency chain (imports + importers) for cross-file context
- **Linter Integration** — Runs language-specific linters (pylint, eslint, clippy, etc.) and feeds results to LLM as signals
- **Rich Terminal Output** — Colored tables, severity trees, and structured findings in the terminal

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/XXUZZWZ/PR_Reviewer.git
cd PR_Reviewer
pip install -e .
```

Or with dev dependencies:

```bash
pip install -e ".[dev]"
```

## Configuration

Create a `config.toml` (see `config.example.toml`):

```toml
[github]
token = "ghp_xxxx"          # GitHub personal access token

[llm]
model = "deepseek-v4-pro"    # LLM model
api_key = "sk-xxxx"          # API key
base_url = "https://api.deepseek.com/anthropic"
```

Or use environment variables:

```bash
export GITHUB_TOKEN="ghp_xxxx"
export ANTHROPIC_API_KEY="sk-xxxx"
```

## Usage

```bash
# Review a PR
pr-review https://github.com/owner/repo/pull/123

# With custom config
pr-review https://github.com/owner/repo/pull/123 -c config.toml

# Save report to file
pr-review https://github.com/owner/repo/pull/123 -o report.json

# Skip linters (LLM-only analysis)
pr-review https://github.com/owner/repo/pull/123 --skip-linters

# Verbose output
pr-review https://github.com/owner/repo/pull/123 -v
```

Also supports short PR URL formats:

```bash
pr-review owner/repo/123
pr-review owner/repo#123
```

## Supported Languages

| Language | Linters |
|----------|---------|
| Python | pylint, mypy, bandit |
| JavaScript / TypeScript | eslint, tsc |
| Java | javac -Xlint, checkstyle |
| Go | go vet, golint, staticcheck |
| Rust | clippy |
| Shell | shellcheck |

Languages without linter support still receive LLM-only analysis.

## Architecture

```
pr-review <url>
  ├── 1. Parse PR URL → (owner, repo, pr_number)
  ├── 2. Fetch PR metadata (files, diff, stats) via GitHub API
  ├── 3. Shallow clone repo at PR head SHA
  ├── 4. Build dependency graph (imports → files, importers → files)
  ├── 5. For each changed file:
  │     ├── Detect language
  │     ├── Run linters (graceful degradation if missing)
  │     ├── Collect dependency context (deps + dependents)
  │     ├── Build prompt with diff + context + linter signals
  │     └── Call LLM → parse structured JSON response
  ├── 6. Generate report (per-file + cross-cutting findings)
  └── 7. Format output (terminal + optional JSON save)
```

## Key Design Decisions

- **Model Choice**: Uses a DeepSeek-compatible Anthropic API with prompt caching. Shared prompt sections (system prompt, PR overview) are cached to reduce costs on multi-file PRs.
- **Per-File over Whole-PR**: Each file is analyzed individually with its dependency context, keeping token budgets manageable while preserving cross-file awareness.
- **Hybrid Analysis**: Linters provide structured, deterministic signals (no false positives on syntax errors). The LLM handles semantic understanding, context-aware reasoning, and cross-cutting concerns.
- **Dependency Chain Context**: For each changed file, the system extracts function/class signatures of imported symbols and call sites of dependent files — giving the LLM enough context to catch breaking changes without blowing the token budget.

## Future Directions

- Support for additional code hosting platforms (GitLab, Bitbucket)
- Custom rule engine for project-specific review policies
- Incremental review mode (review subsequent commits on the same PR)
- Reviewer feedback loop for improving analysis accuracy over time

## License

MIT
