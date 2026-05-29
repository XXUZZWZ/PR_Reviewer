from pydantic import BaseModel


class PRStats(BaseModel):
    total_additions: int
    total_deletions: int
    total_files: int


class ChangedFile(BaseModel):
    path: str
    status: str  # "added", "modified", "removed", "renamed"
    additions: int
    deletions: int
    diff: str = ""
    before_content: str | None = None
    after_content: str | None = None


class PRInfo(BaseModel):
    owner: str
    repo: str
    pr_number: int
    title: str
    description: str = ""
    base_branch: str
    head_branch: str
    base_sha: str
    head_sha: str
    changed_files: list[ChangedFile] = []
    stats: PRStats = PRStats(total_additions=0, total_deletions=0, total_files=0)
