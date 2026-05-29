"""Local git operations — shallow clone, sparse checkout."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

REPOS_DIR = Path.home() / ".pr-reviewer" / "repos"


def ensure_repo_cloned(owner: str, repo: str, head_sha: str, base_sha: str) -> Path:
    """Shallow clone at PR head, fetch base for diffing. Returns repo path."""
    repo_dir = REPOS_DIR / f"{owner}__{repo}"
    clone_url = f"https://github.com/{owner}/{repo}.git"

    if repo_dir.exists():
        return _update_existing(repo_dir, head_sha)

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--depth=50", clone_url, str(repo_dir)])
    _run(["git", "-C", str(repo_dir), "fetch", "origin", head_sha, base_sha])
    _run(["git", "-C", str(repo_dir), "checkout", head_sha])
    return repo_dir


def get_file_content(repo_dir: Path, file_path: str) -> str | None:
    """Read a file from the local repo."""
    target = repo_dir / file_path
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8", errors="replace")


def cleanup_repo(repo_dir: Path) -> None:
    """Remove the local clone."""
    if repo_dir.exists():
        shutil.rmtree(repo_dir)


def _update_existing(repo_dir: Path, head_sha: str) -> Path:
    _run(["git", "-C", str(repo_dir), "fetch", "origin", head_sha])
    _run(["git", "-C", str(repo_dir), "checkout", head_sha])
    return repo_dir


def _run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()
