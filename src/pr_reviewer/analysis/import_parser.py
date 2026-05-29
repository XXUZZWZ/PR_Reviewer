"""Import statement extraction with tree-sitter primary + regex fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pr_reviewer.analysis.language_detector import Language


@dataclass
class ImportStatement:
    module_name: str     # e.g. "os.path" or "./utils/helpers" or "java.util.List"
    symbols: list[str]   # e.g. ["Path", "open"] for "from os.path import Path, open"
    is_relative: bool
    line_number: int


class ImportParser:
    """Language-aware import extraction. Uses regex patterns — tree-sitter is
    a future enhancement for accuracy on complex cases."""

    def extract_imports(self, file_path: Path, language: Language) -> list[ImportStatement]:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            source = f.read()

        if language == Language.PYTHON:
            return _parse_python_imports(source)
        elif language in (Language.JAVASCRIPT, Language.TYPESCRIPT):
            return _parse_js_ts_imports(source)
        elif language == Language.JAVA:
            return _parse_java_imports(source)
        elif language == Language.GO:
            return _parse_go_imports(source)
        elif language == Language.RUST:
            return _parse_rust_imports(source)
        elif language in (Language.C, Language.CPP):
            return _parse_c_cpp_imports(source)
        else:
            return []


# ── Python ──────────────────────────────────────────────

_PY_IMPORT_RE = re.compile(
    r"^(?:from\s+(\S+)\s+)?import\s+(.+)$", re.MULTILINE
)

def _parse_python_imports(source: str) -> list[ImportStatement]:
    imports: list[ImportStatement] = []
    for i, line in enumerate(source.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _PY_IMPORT_RE.match(stripped)
        if not m:
            continue
        module = m.group(1) or ""
        symbols_str = m.group(2)

        if module and module.startswith("."):
            is_relative = True
        else:
            is_relative = False

        symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]
        # Remove aliases: "foo as bar" -> "foo"
        symbols = [s.split(" as ")[0].strip() for s in symbols]

        imports.append(ImportStatement(
            module_name=module,
            symbols=symbols,
            is_relative=is_relative,
            line_number=i,
        ))
    return imports


# ── JavaScript / TypeScript ─────────────────────────────

_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:type\s+)?(?:\{[^}]+\}|[^'"\s;]+)\s*(?:,\s*(?:\{[^}]+\}|[^'"\s;]+))*\s*from\s*)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
_JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]""")

def _parse_js_ts_imports(source: str) -> list[ImportStatement]:
    imports: list[ImportStatement] = []
    for i, line in enumerate(source.split("\n"), 1):
        # ES6 import
        m = _JS_IMPORT_RE.search(line)
        if m:
            module = m.group(1)
            imports.append(ImportStatement(
                module_name=module,
                symbols=[],
                is_relative=module.startswith("."),
                line_number=i,
            ))
            continue
        # require()
        m2 = _JS_REQUIRE_RE.search(line)
        if m2:
            module = m2.group(1)
            imports.append(ImportStatement(
                module_name=module,
                symbols=[],
                is_relative=module.startswith("."),
                line_number=i,
            ))
    return imports


# ── Java ────────────────────────────────────────────────

_JAVA_IMPORT_RE = re.compile(r"^import\s+(static\s+)?(\S+);", re.MULTILINE)

def _parse_java_imports(source: str) -> list[ImportStatement]:
    imports: list[ImportStatement] = []
    for i, line in enumerate(source.split("\n"), 1):
        m = _JAVA_IMPORT_RE.match(line.strip())
        if m:
            full = m.group(2)
            imports.append(ImportStatement(
                module_name=full,
                symbols=[],
                is_relative=False,
                line_number=i,
            ))
    return imports


# ── Go ──────────────────────────────────────────────────

_GO_IMPORT_BLOCK_RE = re.compile(r"import\s*(?:\((.*?)\)|\"([^\"]+)\")", re.DOTALL)
_GO_PKG_RE = re.compile(r'"([^"]+)"')

def _parse_go_imports(source: str) -> list[ImportStatement]:
    imports: list[ImportStatement] = []
    for m in _GO_IMPORT_BLOCK_RE.finditer(source):
        block = m.group(1)
        if block:
            for pkg in _GO_PKG_RE.findall(block):
                imports.append(ImportStatement(
                    module_name=pkg,
                    symbols=[],
                    is_relative=False,
                    line_number=0,
                ))
        elif m.group(2):
            imports.append(ImportStatement(
                module_name=m.group(2),
                symbols=[],
                is_relative=False,
                line_number=0,
            ))
    return imports


# ── Rust ────────────────────────────────────────────────

_RUST_USE_RE = re.compile(r"^use\s+(crate::\S+|self::\S+|super::\S+|\S+::\S+);", re.MULTILINE)

def _parse_rust_imports(source: str) -> list[ImportStatement]:
    imports: list[ImportStatement] = []
    for i, line in enumerate(source.split("\n"), 1):
        m = _RUST_USE_RE.match(line.strip())
        if m:
            module = m.group(1)
            imports.append(ImportStatement(
                module_name=module,
                symbols=[],
                is_relative=module.startswith(("self::", "super::", "crate::")),
                line_number=i,
            ))
    return imports


# ── C / C++ ─────────────────────────────────────────────

_C_INCLUDE_RE = re.compile(r'^#include\s+[<"]([^>"]+)[>"]', re.MULTILINE)

def _parse_c_cpp_imports(source: str) -> list[ImportStatement]:
    imports: list[ImportStatement] = []
    for i, line in enumerate(source.split("\n"), 1):
        m = _C_INCLUDE_RE.match(line.strip())
        if m:
            imports.append(ImportStatement(
                module_name=m.group(1),
                symbols=[],
                is_relative=False,
                line_number=i,
            ))
    return imports
