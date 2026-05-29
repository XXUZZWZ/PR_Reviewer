# AI PR Reviewer — Implementation Plan

## Context

Build an AI-powered CLI tool that reviews GitHub PRs by combining existing language-specific linters (pylint, eslint, javac, etc.) with LLM-based deep analysis. The key architectural insight is **per-file review with dependency chain context** — each changed file is analyzed alongside its imports (dependencies) and importers (dependents), forming a "review group" that gives the LLM enough context to catch cross-file issues without blowing the token budget.

**User's decisions:** CLI tool, local execution, hybrid (linters + LLM), per-file dependency-chain analysis, background task (depth > speed).

## Tech Stack

- **Language:** Python 3.11+ (rich CLI/LLM/linter ecosystem)
- **CLI:** `typer` + `rich`
- **GitHub API:** `PyGithub`
- **LLM SDK:** `anthropic` (via DeepSeek Anthropic-compatible API, `deepseek-v4-pro` primary model, 1M context, prompt caching supported)
- **AST parsing:** `tree-sitter` (primary) + regex fallback
- **Data modeling:** `pydantic` v2
- **Git ops:** subprocess `git`

## Project Structure

```
src/pr_reviewer/
├── main.py                  # Typer CLI, pipeline orchestration
├── config/settings.py       # Pydantic config model, TOML loading
├── github/
│   ├── client.py            # PyGithub wrapper (PR metadata, diff, file content)
│   ├── models.py            # PRInfo, ChangedFile, PRStats
│   └── diff_parser.py       # Parse unified diff → structured hunks
├── analysis/
│   ├── language_detector.py  # Extension → Language enum mapping
│   ├── dependency_graph.py   # Build dependency graph, resolve imports → files, context assembly
│   ├── import_parser.py      # Tree-sitter + regex import extraction per language
│   └── linter/
│       ├── registry.py       # Language → ToolDef mapping, availability check
│       ├── runner.py         # subprocess execution with timeout
│       ├── parsers.py        # Parse per-tool output → LinterFinding
│       └── models.py         # ToolDef, LinterFinding
├── llm/
│   ├── client.py             # Anthropic SDK wrapper, retries, rate limiting
│   ├── prompt_builder.py     # Assemble prompt: diff + deps + linter signals + instructions
│   ├── context_manager.py    # Token budget enforcement, section prioritization
│   └── response_parser.py    # JSON extraction, markdown fence fallback, retry
├── report/
│   ├── generator.py          # Aggregate per-file → PR-level report, cross-cutting findings
│   ├── formatter.py          # Rich terminal output (colored tables, trees)
│   └── models.py             # Report, Finding, FileAnalysis
└── utils/
    ├── git.py                # Shallow clone at PR head SHA, sparese checkout
    └── cache.py              # diskcache for PR metadata, linter output, dependency graph
```

## Core Data Flow

```
1. parse_pr_url(pr_url)                    → (owner, repo, pr_number)
2. fetch_pr_metadata(owner, repo, pr)      → PRInfo + list[ChangedFile]
3. ensure_local_repo(owner, repo, head_sha)→ Path to shallow clone
4. detect_languages(changed_files)         → dict[path, Language]
5. build_dependency_graph(repo_path)       → DependencyGraph (every source file → deps + dependents)
6. FOR EACH changed file:
   a. collect_dependency_context(graph, file) → DependencyContext (imports, importers, transitive)
   b. run_linters(file, language)             → list[LinterFinding]
   c. build_prompt(file, diff, context, findings) → prompt string
   d. call_llm(prompt)                        → FileAnalysis
7. generate_report(all_file_analyses)         → Report
8. format_output(report)                      → Terminal + optional markdown save
```

## Dependency Chain Analysis (Key Design)

For each changed file, assemble a context bundle:

1. **Dependencies** (what this file uses): Extract the function/class signatures of imported symbols — not full file contents. Cross-reference import statements against dependency file ASTs to extract only relevant definitions.

2. **Dependents** (what uses this file): Extract call sites and usage patterns (2-5 lines of context around each usage). Shows where API changes would break consumers.

3. **Transitive** (depth 2): Only included when heavily referenced; summarized in 1-2 sentences.

Example: Changing `src/payment/processor.py` pulls in:
```
Dependencies: src/models/transaction.py (PaymentResult, RefundResult signatures)
Dependents:   src/api/routes.py (call sites at lines 142, 178)
              src/worker/tasks.py (call site at line 89)
```

## Linter Integration

Pre-defined tool registry maps Language → ToolDef list. Each ToolDef has: name, install hint, CLI command builder, output parser. Graceful degradation:
- **Tool not installed** → log warning, skip
- **Tool returns no findings** → positive signal in prompt ("pylint: no issues")
- **No tools for language** → LLM-only analysis

Prioritized tool list (extensible):
| Language | Tools |
|----------|-------|
| Python | pylint, mypy, bandit |
| JS/TS | eslint, tsc |
| Java | javac -Xlint, checkstyle |
| Go | go vet, golint, staticcheck |
| Rust | clippy |
| Shell | shellcheck |

## LLM Prompt Strategy

**Prompt sections (in order, for caching):**
1. System prompt (cached) — reviewer instructions, JSON output schema
2. PR overview (cached) — title, description, stats
3. File analysis (per-file) — diff + dependency context + linter results

**Token budget:** 60k target per file call. Priority: linter findings > diff hunks near linter hits > dependency context > remaining diff > file structure.

**Output:** Structured JSON with severity/category/confidence/suggestion. Fallback: retry with stricter prompt if malformed.

## Implementation Order (6 phases)

### Phase 1: Foundation
- Scaffold project (pyproject.toml, entry points)
- Configuration module (TOML + env vars)
- GitHub API client (PR metadata, diff fetch)
- Diff parser (unified diff → hunks)
- **Verify:** `pr-review --help` works, can fetch real PR data

### Phase 2: Dependency Analysis
- Language detection (extension mapping)
- Import parser (tree-sitter for Python/JS/Java/Go + regex fallback)
- Dependency graph builder (full repo scan → deps + dependents)
- Local git operations (shallow clone)
- **Verify:** Dependency graph is correct for a known small repo

### Phase 3: Linter Integration
- Tool registry with default ToolDefs
- Linter runner (subprocess with timeout)
- Output parsers (JSON parsers per tool)
- **Verify:** Linter findings extracted correctly for each language

### Phase 4: LLM Integration
- Prompt builder (assemble all sections)
- Context manager (token budget, truncation)
- Anthropic SDK client (with retry/backoff)
- Response parser (JSON + fallbacks)
- **Verify:** Prompt looks correct, LLM returns valid structured JSON

### Phase 5: Report & Orchestration
- Report generator (per-file aggregation, cross-cutting findings detection)
- Terminal formatter (rich colored tables)
- Main pipeline wiring (end-to-end flow)
- **Verify:** Full run on a real PR produces correct report

### Phase 6: Polish
- Error handling (rate limits, network errors, malformed responses)
- Linter timeout/error graceful degradation
- Caching (diskcache for repeated runs)
- README with usage examples

## Verification Strategy

1. **Unit tests:** language detection, diff parsing, import extraction, linter output parsing, response parsing
2. **Integration tests:** dependency graph on known repos, linter runner on fixture files, prompt builder with sample inputs
3. **End-to-end:** Run on real GitHub PRs (open-source) and manually verify report quality
4. **Error resilience:** Mock network failures, rate limits, missing tools, and malformed LLM responses

## Key Design Decisions

- **Per-file over whole-PR:** Token budget manageable per file, linter signals file-aligned, dependency context fills the cross-file gap
- **Tree-sitter over regex:** Correct parse trees across languages; regex as fallback for unsupported languages
- **Shallow clone over API-only:** Enables filesystem search for dependency resolution and linters that need project structure
- **Structured JSON output:** Enables programmatic downstream processing, confidence scoring, severity filtering
- **Claude Sonnet 4:** 200k context, strong code understanding, prompt caching for shared sections → ~5x cost reduction on multi-file PRs
- **Sequential over parallel:** Simpler; dependency analysis from earlier files can inform later files
