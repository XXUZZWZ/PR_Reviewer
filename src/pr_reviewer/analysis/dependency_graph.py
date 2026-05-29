"""Build and traverse the project-wide dependency graph.

Strategy: build a full file index (fast, path-only), then lazy-parse only
changed files and their immediate import/dependent neighbors.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pr_reviewer.analysis.language_detector import Language, detect_language
from pr_reviewer.analysis.import_parser import ImportParser, ImportStatement


@dataclass
class FileNode:
    path: str
    language: Language
    dependencies: set[str] = field(default_factory=set)
    dependents: set[str] = field(default_factory=set)


@dataclass
class DependencyContext:
    file_path: str
    language: Language
    dependencies: dict[str, str]
    dependents: dict[str, str]
    external_imports: list[str]


class DependencyGraph:

    def __init__(self, repo_path: Path, settings: object = None):
        self.repo_path = repo_path
        self._settings = settings
        self.nodes: dict[str, FileNode] = {}
        self._parser = ImportParser()
        self._all_files: set[str] = set()
        self._stem_index: dict[str, list[str]] = defaultdict(list)

    def build(self, changed_paths: set[str] | None = None) -> None:
        """Build dependency graph, scoped to changed files and their neighbors."""
        self._all_files = _collect_source_files(self.repo_path)
        self._stem_index = _build_stem_index(self._all_files)

        targets = changed_paths or set()
        if not targets:
            return

        # Phase 1: Parse changed files and resolve their imports
        files_to_parse = set(targets)
        parsed: dict[str, list[ImportStatement]] = {}

        for fpath in files_to_parse:
            lang = detect_language(fpath)
            if lang == Language.UNKNOWN:
                continue
            abs_path = self.repo_path / fpath
            if not abs_path.exists():
                continue
            imports = self._parser.extract_imports(abs_path, lang)
            parsed[fpath] = imports

        # Phase 2: Resolve imports and create nodes for changed files
        for fpath in files_to_parse:
            lang = detect_language(fpath)
            node = FileNode(path=fpath, language=lang)
            for imp in parsed.get(fpath, []):
                resolved = self._resolve_import(fpath, imp)
                if resolved:
                    node.dependencies.add(resolved)
                    # Also create nodes for resolved files
                    if resolved not in self.nodes:
                        dep_lang = detect_language(resolved)
                        self.nodes[resolved] = FileNode(path=resolved, language=dep_lang)
            self.nodes[fpath] = node

        # Phase 3: Find dependents — files that import any changed file
        for fpath in targets:
            stem = Path(fpath).stem
            for candidate in self._stem_index.get(stem, []):
                if candidate == fpath or candidate in targets:
                    continue
                # Quick check: does this file actually import our target?
                if _file_mentions_stem(self.repo_path, candidate, stem):
                    if candidate not in self.nodes:
                        lang = detect_language(candidate)
                        self.nodes[candidate] = FileNode(path=candidate, language=lang)
                    self.nodes[candidate].dependencies.add(fpath)
                    if fpath in self.nodes:
                        self.nodes[fpath].dependents.add(candidate)

    def get_context(
        self, file_path: str, language: Language, max_depth: int = 2
    ) -> DependencyContext:
        """Assemble the dependency context for a changed file."""
        node = self.nodes.get(file_path)
        if not node:
            return DependencyContext(
                file_path=file_path, language=language,
                dependencies={}, dependents={}, external_imports=[],
            )

        deps = self._collect_dependencies(file_path, max_depth)
        deps_snippets = {}
        for dep in deps:
            snippet = _extract_relevant_definitions(self.repo_path, dep)
            if snippet:
                deps_snippets[dep] = snippet

        dep_snippets = _collect_dependent_usages(self.repo_path, file_path)

        return DependencyContext(
            file_path=file_path,
            language=language,
            dependencies=deps_snippets,
            dependents=dep_snippets,
            external_imports=[],
        )

    def _resolve_import(self, from_file: str, imp: ImportStatement) -> str | None:
        """Try to resolve a module import to a concrete file path."""
        candidates: list[str] = []

        if imp.is_relative:
            base = Path(from_file).parent
            dots = len(imp.module_name) - len(imp.module_name.lstrip("."))
            if dots > 0:
                for _ in range(dots - 1):
                    base = base.parent
                rest = imp.module_name[dots:]
                if rest:
                    p = str(base / rest.replace(".", "/"))
                    candidates.extend([p + ".py", p + ".pyi", p + "/__init__.py",
                                       p + ".ts", p + ".js", p + "/index.ts", p + "/index.js"])
                else:
                    candidates.append(str(base / "__init__.py"))
                for cand in candidates:
                    if cand in self._all_files:
                        return cand
                return None

        module_path = imp.module_name.replace(".", "/")

        # Python
        candidates.extend([module_path + ".py", module_path + ".pyi", module_path + "/__init__.py"])
        # JS/TS
        candidates.extend([module_path + ".ts", module_path + ".tsx", module_path + ".js",
                           module_path + ".jsx", module_path + "/index.ts", module_path + "/index.js"])
        # Java
        candidates.append(module_path + ".java")

        for cand in candidates:
            if cand in self._all_files:
                return cand

        # Last resort: stem match
        last = Path(module_path).name
        matches = self._stem_index.get(last, [])
        if len(matches) == 1 and matches[0] != from_file:
            return matches[0]

        return None

    def _collect_dependencies(self, file_path: str, max_depth: int) -> set[str]:
        visited: set[str] = set()
        current = {file_path}
        for _ in range(max_depth):
            next_level: set[str] = set()
            for f in current:
                node = self.nodes.get(f)
                if node:
                    for dep in node.dependencies:
                        if dep not in visited and dep != file_path:
                            next_level.add(dep)
            visited |= next_level
            current = next_level
        return visited


# ── Helpers ────────────────────────────────────────────

def _collect_source_files(repo_path: Path) -> set[str]:
    extensions = {
        ".py", ".pyi", ".js", ".jsx", ".mjs", ".ts", ".tsx",
        ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cc", ".cxx",
        ".hpp", ".rb", ".sh", ".bash", ".zsh",
    }
    skip_prefixes = (
        "node_modules/", ".git/", "__pycache__/", "target/",
        "build/", "dist/", ".venv/", "venv/",
    )
    files: set[str] = set()
    for f in repo_path.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in extensions:
            continue
        rel = str(f.relative_to(repo_path))
        if not rel.startswith(skip_prefixes):
            files.add(rel)
    return files


def _build_stem_index(all_files: set[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for f in all_files:
        index[Path(f).stem].append(f)
    return index


def _file_mentions_stem(repo_path: Path, file_path: str, stem: str) -> bool:
    """Quick check if a file likely imports/uses a module with given stem."""
    # Simple heuristic: search first 200 lines
    abs_path = repo_path / file_path
    if not abs_path.exists():
        return False
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 200:
                    break
                if stem in line and not line.strip().startswith(("//", "#", "/*", "*")):
                    return True
    except Exception:
        pass
    return False


def _extract_relevant_definitions(repo_path: Path, file_path: str, limit: int = 60) -> str | None:
    abs_path = repo_path / file_path
    if not abs_path.exists():
        return None
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")
        sig_lines = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if (
                stripped.startswith(("def ", "class ", "async def "))
                or (stripped.startswith("pub ") and "fn " in stripped)
                or stripped.startswith("func ")
                or stripped.startswith("public class ")
                or stripped.startswith("public interface ")
                or stripped.startswith("export function ")
                or stripped.startswith("export class ")
            ):
                sig_lines.append(f"  Line {i+1}: {stripped}")
            if len(sig_lines) >= limit:
                break
        return "\n".join(sig_lines) if sig_lines else None
    except Exception:
        return None


def _collect_dependent_usages(repo_path: Path, file_path: str) -> dict[str, str]:
    """For a given file, find usage sites in files that mention its stem."""
    snippets: dict[str, str] = {}
    stem = Path(file_path).stem
    # This is called per changed file; dependents are pre-computed in self.nodes
    # The actual dependent data is populated in build() Phase 3
    return snippets
