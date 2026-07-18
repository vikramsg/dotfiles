from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ocint._models import CliOutput


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
    command_timeout_seconds: int = Field(default=600, ge=1)
    command_output_bytes: int = Field(default=65536, ge=1024)


class LifecycleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    startup_delay_seconds: int = Field(default=60, ge=1)
    inactive_interval_seconds: int = Field(default=900, ge=1)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=5, ge=1)


class OpenCodeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_url: HttpUrl = HttpUrl("http://127.0.0.1:4097")
    username: str = "opencode"
    request_timeout_seconds: int = Field(default=30, ge=1)
    expected_version: Literal["1.17.20"] = "1.17.20"
    executable: Path = Path("/usr/bin/opencode")
    config_file: Path
    xdg_config_home: Path
    xdg_data_home: Path
    startup_timeout_seconds: int = Field(default=120, ge=1)
    shutdown_timeout_seconds: int = Field(default=10, ge=1)

    @field_validator("executable", "config_file", "xdg_config_home", "xdg_data_home")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class ApiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8732, ge=1, le=65535)


class GitHubConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_url: HttpUrl = HttpUrl("https://api.github.com")
    issue_label: str = "ocint"
    agent_actor: str


class GitConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    ssh_executable: Path
    identity_file: Path
    known_hosts_file: Path

    @field_validator("ssh_executable", "identity_file", "known_hosts_file")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class DaemonConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path
    mirror_root: Path
    worktree_root: Path
    repositories: tuple[RepositoryConfig, ...] = Field(min_length=1)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    opencode: OpenCodeConfig = Field(default_factory=OpenCodeConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    git: GitConfig
    idle_timeout_seconds: int = Field(default=60, ge=1)

    @field_validator("database_path", "mirror_root", "worktree_root")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()

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
    github_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_GITHUB_TOKEN")
    xdg_config_home: Path | None = Field(
        default=None, validation_alias=AliasChoices("XDG_CONFIG_HOME", "OCINT_DAEMON_XDG_CONFIG_HOME")
    )
    execution_path: str = Field(default="/usr/local/bin:/usr/bin:/bin", validation_alias="PATH")
    execution_lang: str = Field(default="C.UTF-8", validation_alias=AliasChoices("LANG", "LC_ALL"))

    def config_path(self, home: Path) -> Path:
        if self.config is not None:
            return self.config.expanduser().resolve()
        base = self.xdg_config_home if self.xdg_config_home is not None else home / ".config"
        return (base / "ocint" / "daemon.toml").resolve()


@dataclass
class DaemonContext:
    output: CliOutput
    home: Path
    settings: DaemonSettings
    config_home: Path
    data_home: Path
    state_home: Path
    user: str
    environment: dict[str, str]
    _config: DaemonConfig | None = field(default=None, init=False, repr=False)

    @classmethod
    def create(
        cls,
        output: CliOutput,
        home: Path,
        environment: Mapping[str, str],
        settings: DaemonSettings | None = None,
    ) -> DaemonContext:
        resolved_settings = settings or DaemonSettings()
        config_home = resolved_settings.xdg_config_home or Path(environment.get("XDG_CONFIG_HOME", home / ".config"))
        return cls(
            output=output,
            home=home.resolve(),
            settings=resolved_settings,
            config_home=config_home.expanduser().resolve(),
            data_home=Path(environment.get("XDG_DATA_HOME", home / ".local" / "share")).expanduser().resolve(),
            state_home=Path(environment.get("XDG_STATE_HOME", home / ".local" / "state")).expanduser().resolve(),
            user=environment.get("USER", ""),
            environment=dict(environment),
        )

    @property
    def config_path(self) -> Path:
        return self.settings.config_path(self.home)

    def config(self) -> DaemonConfig:
        if self._config is None:
            with self.config_path.open("rb") as stream:
                self._config = DaemonConfig.model_validate(tomllib.load(stream))
        return self._config
