from __future__ import annotations

from github import Github, GithubException
from github.PullRequest import PullRequest

from pr_reviewer.config.settings import GitHubConfig, Settings
from pr_reviewer.github.models import PRInfo, PRStats, ChangedFile


class GitHubClient:
    """Wraps PyGithub for PR data fetching."""

    def __init__(self, config: GitHubConfig):
        self._base_url = config.base_url
        token = config.token
        if not token:
            raise ValueError("GitHub token not configured. Set GITHUB_TOKEN env var or in config file.")
        self._client = Github(token, base_url=config.base_url)

    @classmethod
    def from_settings(cls, settings: Settings) -> GitHubClient:
        return cls(settings.github)

    def fetch_pr(self, owner: str, repo: str, pr_number: int) -> PRInfo:
        repo_obj = self._client.get_repo(f"{owner}/{repo}")
        pr = repo_obj.get_pull(pr_number)

        stats = PRStats(
            total_additions=pr.additions,
            total_deletions=pr.deletions,
            total_files=pr.changed_files,
        )

        changed_files: list[ChangedFile] = []
        for pf in pr.get_files():
            changed_files.append(ChangedFile(
                path=pf.filename,
                status=pf.status,
                additions=pf.additions,
                deletions=pf.deletions,
                diff=pf.patch or "",
            ))

        return PRInfo(
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            title=pr.title,
            description=pr.body or "",
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            base_sha=pr.base.sha,
            head_sha=pr.head.sha,
            changed_files=changed_files,
            stats=stats,
        )

    def fetch_file_content(self, owner: str, repo: str, path: str, ref: str) -> str:
        repo_obj = self._client.get_repo(f"{owner}/{repo}")
        try:
            content = repo_obj.get_contents(path, ref=ref)
            return content.decoded_content.decode("utf-8")
        except GithubException:
            return ""


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Extract (owner, repo, pr_number) from a GitHub PR URL.

    Supports:
      - https://github.com/owner/repo/pull/123
      - owner/repo/123
      - owner/repo#123
    """
    import re

    url = url.strip()

    full_url = re.match(
        r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$",
        url,
    )
    if full_url:
        return full_url.group(1), full_url.group(2).removesuffix(".git"), int(full_url.group(3))

    short = re.match(r"^([^/]+)/([^/]+?)/(\d+)$", url)
    if short:
        return short.group(1), short.group(2), int(short.group(3))

    alt = re.match(r"^([^/]+)/([^/]+?)#(\d+)$", url)
    if alt:
        return alt.group(1), alt.group(2), int(alt.group(3))

    raise ValueError(f"Could not parse PR URL: {url}")
