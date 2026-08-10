from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ocint._models import CliOutput
from ocint.daemon.coordinator import CoordinatorConfig, CoordinatorSlackConfig
from ocint.daemon.git import GitConfig
from ocint.daemon.github import GitHubConfig
from ocint.daemon.models import GitHubLogin, GitRepository
from ocint.daemon.opencode import OpenCodeConfig


class RepositoryConfig(GitRepository):
    model_config = ConfigDict(frozen=True)

    github_repository: str
    description: str = Field(min_length=1)
    author_name: str
    author_email: str
    actors: frozenset[GitHubLogin] = frozenset()
    checks: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)

    @field_validator("name", "description", "github_repository", "default_branch")
    @classmethod
    def reject_blank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("repository metadata must not be blank")
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
    inactive_interval_seconds: int = Field(default=600, ge=1)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=5, ge=1)


class ApiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8732, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        try:
            loopback = ip_address(value).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("daemon API host must be a loopback IP address")
        return value


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
    coordinator: CoordinatorConfig
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
        roots = (self.coordinator.workspace_root, self.mirror_root, self.worktree_root)
        for index, left in enumerate(roots):
            for right in roots[index + 1 :]:
                if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                    raise ValueError("coordinator workspace_root, mirror_root, and worktree_root must be disjoint")
        opencode_paths = (
            (self.opencode.config_file, self.coordinator.opencode.config_file),
            (self.opencode.xdg_config_home, self.coordinator.opencode.xdg_config_home),
            (self.opencode.xdg_data_home, self.coordinator.opencode.xdg_data_home),
        )
        if any(job_path.resolve() == coordinator_path.resolve() for job_path, coordinator_path in opencode_paths):
            raise ValueError("coordinator OpenCode config and data paths must be isolated from the job runtime")
        opencode_hosts = (self.opencode.server_url.host, self.coordinator.opencode.server_url.host)
        for host in opencode_hosts:
            try:
                loopback = host is not None and ip_address(host).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise ValueError("OpenCode servers must use loopback IP addresses")
        ports = (
            self.api.port,
            self.coordinator.ingress.port,
            self.opencode.server_url.port,
            self.coordinator.opencode.server_url.port,
        )
        if any(port is None for port in ports) or len(set(ports)) != len(ports):
            raise ValueError("daemon API, coordinator ingress, and OpenCode ports must be distinct")
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
    slack_bot_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_SLACK_BOT_TOKEN")
    slack_signing_secret: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_SLACK_SIGNING_SECRET")
    ngrok_url: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("OCINT_NGROK_URL", "OCINT_DAEMON_NGROK_URL")
    )
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
