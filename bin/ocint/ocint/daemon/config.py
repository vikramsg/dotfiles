from __future__ import annotations

import re
from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RepositoryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    remote_url: str
    default_branch: str = "main"
    github_repository: str
    author_name: str
    author_email: str
    actors: frozenset[str] = Field(default_factory=frozenset)
    checks: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)

    @field_validator("remote_url")
    @classmethod
    def validate_ssh_remote(cls, value: str) -> str:
        scp_style = re.fullmatch(r"[^@\s/:]+@[^\s/:]+:.+", value)
        ssh_url = re.fullmatch(r"ssh://(?:[^@/\s]+@)?[^/:\s]+(?::[0-9]+)?/.+", value)
        if scp_style is None and ssh_url is None:
            raise ValueError("repository remote_url must use SSH (git@host:path or ssh://host/path)")
        return value


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    capacity: int = Field(default=1, ge=1)
    job_timeout_seconds: int = Field(default=3600, ge=1)
    shutdown_timeout_seconds: int = Field(default=30, ge=1)
    command_timeout_seconds: int = Field(default=900, ge=1)
    command_output_bytes: int = Field(default=65536, ge=1024)


class OpenCodeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_url: HttpUrl = HttpUrl("http://127.0.0.1:4096")
    username: str = "opencode"
    request_timeout_seconds: int = Field(default=30, ge=1)
    expected_version: str = "1.17.20"


class ApiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8732, ge=1, le=65535)


class GitHubConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_url: HttpUrl = HttpUrl("https://api.github.com")


class DaemonConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path
    mirror_root: Path
    worktree_root: Path
    repositories: tuple[RepositoryConfig, ...]
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    opencode: OpenCodeConfig = Field(default_factory=OpenCodeConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)

    @model_validator(mode="after")
    def validate_registry_and_roots(self) -> DaemonConfig:
        names = [item.name for item in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("repository names must be unique")
        if self.mirror_root.resolve() == self.worktree_root.resolve():
            raise ValueError("mirror_root and worktree_root must differ")
        return self

    def repository(self, name: str) -> RepositoryConfig:
        for item in self.repositories:
            if item.name == name:
                return item
        raise ValueError(f"repository is not configured: {name}")


class DaemonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCINT_DAEMON_", extra="ignore", populate_by_name=True, frozen=True)

    config: Path | None = Field(default=None, validation_alias="OCINT_DAEMON_CONFIG")
    api_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_API_TOKEN")
    opencode_password: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_OPENCODE_PASSWORD")
    github_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_GITHUB_TOKEN")
    xdg_config_home: Path | None = Field(
        default=None, validation_alias=AliasChoices("XDG_CONFIG_HOME", "OCINT_DAEMON_XDG_CONFIG_HOME")
    )
    execution_path: str = Field(default="/usr/local/bin:/usr/bin:/bin", validation_alias="PATH")
    execution_lang: str = Field(default="C.UTF-8", validation_alias=AliasChoices("LANG", "LC_ALL"))
    ssh_auth_sock: str = Field(default="", validation_alias="SSH_AUTH_SOCK")

    def config_path(self, home: Path) -> Path:
        if self.config is not None:
            return self.config.expanduser().resolve()
        base = self.xdg_config_home if self.xdg_config_home is not None else home / ".config"
        return (base / "ocint" / "daemon.toml").resolve()
