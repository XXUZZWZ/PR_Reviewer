"""Build and traverse the project-wide dependency graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pr_reviewer.analysis.language_detector import Language, detect_language
from pr_reviewer.analysis.import_parser import ImportParser, ImportStatement


@dataclass
class FileNode:
    path: str                # relative to repo root
    language: Language
    dependencies: set[str] = field(default_factory=set)  # paths this file imports
    dependents: set[str] = field(default_factory=set)    # paths that import this file


@dataclass
class DependencyContext:
    """Context bundle for a single changed file."""
    file_path: str
    language: Language
    dependencies: dict[str, str]    # dep_path -> relevant snippet/signature
    dependents: dict[str, str]      # dep_path -> usage site context
    external_imports: list[str]     # third-party / stdlib module names


class DependencyGraph:
    """Full-repo import dependency graph.

    Built once per PR analysis run, then queried per changed file.
    """

    def __init__(self, repo_path: Path, settings: object = None):
        self.repo_path = repo_path
        self._settings = settings
        self.nodes: dict[str, FileNode] = {}
        self._parser = ImportParser()

    def build(self, changed_paths: set[str] | None = None) -> None:
        """Scan all source files in repo and build dependency graph.

        If changed_paths is provided, only parse those files + any files
        they import or are imported by. Otherwise parse everything.
        """
        all_files = self._collect_source_files()

        # Phase 1: extract all imports
        file_imports: dict[str, list[ImportStatement]] = {}
        for fpath in all_files:
            lang = detect_language(fpath)
            if lang == Language.UNKNOWN:
                continue
            abs_path = self.repo_path / fpath
            imports = self._parser.extract_imports(abs_path, lang)
            file_imports[fpath] = imports

        # Phase 2: resolve imports to file paths
        for fpath, imports in file_imports.items():
            lang = detect_language(fpath)
            node = FileNode(path=fpath, language=lang)
            for imp in imports:
                resolved = self._resolve_import(fpath, imp, all_files)
                if resolved:
                    node.dependencies.add(resolved)
            self.nodes[fpath] = node

        # Phase 3: build reverse index (dependents)
        for fpath, node in self.nodes.items():
            for dep_path in node.dependencies:
                if dep_path in self.nodes:
                    self.nodes[dep_path].dependents.add(fpath)

    def get_context(
        self, file_path: str, language: Language, max_depth: int = 2
    ) -> DependencyContext:
        """Assemble the dependency context for a changed file."""
        node = self.nodes.get(file_path)
        if not node:
            return DependencyContext(
                file_path=file_path,
                language=language,
                dependencies={},
                dependents={},
                external_imports=[],
            )

        deps = self._collect_dependencies(file_path, max_depth)
        deps_snippets: dict[str, str] = {}
        for dep in deps:
            snippet = self._extract_relevant_definitions(dep, deps)
            if snippet:
                deps_snippets[dep] = snippet

        dep_snippets = self._collect_dependent_usages(file_path)

        return DependencyContext(
            file_path=file_path,
            language=language,
            dependencies=deps_snippets,
            dependents=dep_snippets,
            external_imports=[],
        )

    def _collect_source_files(self) -> set[str]:
        """Walk repo and return all source file paths relative to repo root."""
        extensions = {
            ".py", ".pyi", ".js", ".jsx", ".mjs", ".ts", ".tsx",
            ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cc", ".cxx",
            ".hpp", ".rb", ".sh", ".bash", ".zsh",
        }
        files: set[str] = set()
        for f in self.repo_path.rglob("*"):
            if f.is_file() and f.suffix.lower() in extensions:
                rel = str(f.relative_to(self.repo_path))
                # Skip common non-source dirs
                if not any(rel.startswith(d) for d in (
                    "node_modules/", ".git/", "__pycache__/", "target/",
                    "build/", "dist/", ".venv/", "venv/",
                )):
                    files.add(rel)
        return files

    def _resolve_import(
        self, from_file: str, imp: ImportStatement, all_files: set[str]
    ) -> str | None:
        """Try to resolve a module import to a concrete file path."""
        candidates: list[str] = []

        # Relative imports: resolve relative to the importing file
        if imp.is_relative:
            base = Path(from_file).parent
            parts = imp.module_name.split(".")
            # Count leading dots for Python-style relative imports
            dots = len(imp.module_name) - len(imp.module_name.lstrip("."))
            if dots > 0:
                for _ in range(dots - 1):
                    base = base.parent
                rest = imp.module_name[dots:]
                if rest:
                    candidates.append(str(base / rest.replace(".", "/")) + ".py")
                    candidates.append(str(base / rest.replace(".", "/")) + "/__init__.py")
                else:
                    candidates.append(str(base / "__init__.py"))
                for cand in candidates:
                    if cand in all_files:
                        return cand
                return None

        # Non-relative: try standard resolution strategies
        module_path = imp.module_name.replace(".", "/")

        # Python-style package or module
        candidates.extend([
            module_path + ".py",
            module_path + ".pyi",
            module_path + "/__init__.py",
        ])

        # JS/TS
        candidates.extend([
            module_path + ".js",
            module_path + ".ts",
            module_path + "/index.js",
            module_path + "/index.ts",
        ])

        # Java
        candidates.append(module_path + ".java")

        # Generic: try the module_path as-is
        if "." not in module_path and "/" in module_path:
            for ext in (".py", ".js", ".ts", ".java", ".go", ".rs", ".rb"):
                candidates.append(module_path + ext)

        for cand in candidates:
            if cand in all_files:
                return cand

        # Try matching just the last component
        last = Path(module_path).name
        matches = [f for f in all_files if Path(f).stem == last and f != from_file]
        if len(matches) == 1:
            return matches[0]

        return None

    def _collect_dependencies(self, file_path: str, max_depth: int) -> set[str]:
        """Collect transitive dependencies up to max_depth."""
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

    def _collect_dependent_usages(self, file_path: str) -> dict[str, str]:
        """For each dependent file, extract the lines that reference this file."""
        snippets: dict[str, str] = {}
        node = self.nodes.get(file_path)
        if not node:
            return snippets

        # Get the basename of the changed file to search for usage patterns
        stem = Path(file_path).stem

        for dep_path in node.dependents:
            abs_path = self.repo_path / dep_path
            if not abs_path.exists():
                continue
            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                lines = content.split("\n")
                usage_lines: list[str] = []
                for i, line in enumerate(lines):
                    if stem in line and not line.strip().startswith(("import ", "from ", "//", "/*")):
                        # Include surrounding context (2 lines each side)
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        usage_lines.append(f"  Line {i+1}:")
                        for j in range(start, end):
                            prefix = ">>> " if j == i else "    "
                            usage_lines.append(f"  {prefix}{lines[j]}")
                        if len(usage_lines) > 50:
                            break
                if usage_lines:
                    snippets[dep_path] = "\n".join(usage_lines[:60])
            except Exception:
                continue
        return snippets

    def _extract_relevant_definitions(
        self, file_path: str, limit: int = 80
    ) -> str | None:
        """Extract function/class signatures from a file (top-level only)."""
        abs_path = self.repo_path / file_path
        if not abs_path.exists():
            return None
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            sig_lines: list[str] = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Match function/class/method definitions
                if (
                    stripped.startswith(("def ", "class ", "async def "))
                    or "fn " in stripped and stripped.startswith("pub ")
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
