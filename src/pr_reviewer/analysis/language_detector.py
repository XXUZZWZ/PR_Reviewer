from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    GO = "go"
    RUST = "rust"
    C = "c"
    CPP = "cpp"
    SHELL = "shell"
    RUBY = "ruby"
    YAML = "yaml"
    DOCKERFILE = "dockerfile"
    UNKNOWN = "unknown"


EXTENSION_MAP: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".c": Language.C,
    ".h": Language.C,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".hpp": Language.CPP,
    ".sh": Language.SHELL,
    ".bash": Language.SHELL,
    ".zsh": Language.SHELL,
    ".rb": Language.RUBY,
    ".yml": Language.YAML,
    ".yaml": Language.YAML,
}

FILENAME_MAP: dict[str, Language] = {
    "Dockerfile": Language.DOCKERFILE,
    "Makefile": Language.SHELL,
}


def detect_language(file_path: str) -> Language:
    """Detect programming language from a file path."""
    from pathlib import Path

    p = Path(file_path)
    filename = p.name

    if filename in FILENAME_MAP:
        return FILENAME_MAP[filename]

    suffix = p.suffix.lower()
    if suffix in EXTENSION_MAP:
        return EXTENSION_MAP[suffix]

    # Handle compound extensions: .d.ts -> typescript
    if filename.endswith(".d.ts"):
        return Language.TYPESCRIPT

    return Language.UNKNOWN
