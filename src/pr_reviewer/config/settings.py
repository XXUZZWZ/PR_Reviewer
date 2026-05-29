from __future__ import annotations

from pydantic import BaseModel, Field
from pathlib import Path
import os
import tomllib


class GitHubConfig(BaseModel):
    token: str = ""
    base_url: str = "https://api.github.com"


class LLMConfig(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-pro"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/anthropic"
    max_output_tokens: int = 8192
    temperature: float = 0.3


class AnalysisConfig(BaseModel):
    max_dependency_depth: int = 2
    include_test_files: bool = True


class LinterConfig(BaseModel):
    enabled: bool = True
    timeout_seconds: int = 60


class ReportConfig(BaseModel):
    terminal_verbosity: str = "default"
    save_path: str = ""


class Settings(BaseModel):
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    linters: LinterConfig = Field(default_factory=LinterConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Settings:
        settings = cls()

        # Merge from config file
        if config_path and Path(config_path).exists():
            with open(config_path, "rb") as f:
                data = tomllib.load(f)
            settings = cls._merge(settings, data)

        # Override from env vars
        settings = cls._apply_env(settings)

        return settings

    @classmethod
    def _merge(cls, base: Settings, data: dict) -> Settings:
        merged = base.model_dump()
        for section in ("github", "llm", "analysis", "linters", "report"):
            if section in data:
                merged[section].update(data[section])
        return cls(**merged)

    @classmethod
    def _apply_env(cls, settings: Settings) -> Settings:
        if gh_token := os.environ.get("GITHUB_TOKEN"):
            settings.github.token = gh_token
        if llm_key := os.environ.get("ANTHROPIC_API_KEY"):
            settings.llm.api_key = llm_key
        return settings
