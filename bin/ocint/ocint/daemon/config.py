from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RepositoryConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    remote_url: str
    default_branch: str = "main"
    actors: frozenset[str] = Field(default_factory=frozenset)
    checks: list[list[str]] = Field(default_factory=list)
    github_repository: str = ""


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    capacity: int = Field(default=1, ge=1)
    lease_seconds: int = Field(default=120, ge=5)
    heartbeat_seconds: int = Field(default=30, ge=1)
    max_attempts: int = Field(default=2, ge=1)
    poll_seconds: float = Field(default=1.0, gt=0)
    job_timeout_seconds: int = Field(default=3600, ge=1)
    shutdown_timeout_seconds: int = Field(default=30, ge=1)
    command_timeout_seconds: int = Field(default=900, ge=1)
    command_output_bytes: int = Field(default=65536, ge=1024)
    outbox_lease_seconds: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def validate_heartbeat(self) -> SchedulerConfig:
        if self.heartbeat_seconds >= self.lease_seconds:
            raise ValueError("scheduler heartbeat_seconds must be less than lease_seconds")
        return self


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


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    github_api_url: HttpUrl = HttpUrl("https://api.github.com")
    slack_api_url: HttpUrl = HttpUrl("https://slack.com/api")
    slack_socket_url: HttpUrl = HttpUrl("https://slack.com/api/apps.connections.open")


class GitHubChannelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    github_repository: str
    label: str = "ocint"
    poll_seconds: float = Field(default=30, gt=0)


class SlackChannelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    socket_mode: bool = True
    channel_repositories: Mapping[str, str] = Field(default_factory=dict)


class ChannelsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    github: list[GitHubChannelConfig] = Field(default_factory=list)
    slack: SlackChannelConfig = Field(default_factory=SlackChannelConfig)


class DaemonConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    database_path: Path
    mirror_root: Path
    worktree_root: Path
    repositories: list[RepositoryConfig]
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    opencode: OpenCodeConfig = Field(default_factory=OpenCodeConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    providers: ProviderConfig = Field(default_factory=ProviderConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    retention_seconds: int = Field(default=86400, ge=0)

    @model_validator(mode="after")
    def validate_registry_and_roots(self) -> DaemonConfig:
        names = [repository.name for repository in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("repository names must be unique")
        if self.mirror_root.resolve() == self.worktree_root.resolve():
            raise ValueError("mirror_root and worktree_root must differ")
        return self

    def repository(self, name: str) -> RepositoryConfig:
        for repository in self.repositories:
            if repository.name == name:
                return repository
        raise ValueError(f"repository is not configured: {name}")


class DaemonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCINT_DAEMON_", extra="ignore", populate_by_name=True, frozen=True)

    config: Path | None = Field(default=None, validation_alias="OCINT_DAEMON_CONFIG")
    opencode_password: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_OPENCODE_PASSWORD")
    api_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_API_TOKEN")
    github_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_GITHUB_TOKEN")
    slack_token: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_SLACK_TOKEN")
    slack_signing_secret: SecretStr = Field(default=SecretStr(""), validation_alias="OCINT_DAEMON_SLACK_SIGNING_SECRET")
    xdg_config_home: Path | None = Field(
        default=None, validation_alias=AliasChoices("XDG_CONFIG_HOME", "OCINT_DAEMON_XDG_CONFIG_HOME")
    )
    execution_path: str = Field(default="/usr/local/bin:/usr/bin:/bin", validation_alias="PATH")
    execution_lang: str = Field(default="C.UTF-8", validation_alias=AliasChoices("LANG", "LC_ALL"))
    publication_home: Path = Field(default=Path("/var/empty"), validation_alias="HOME")
    ssh_auth_sock: str = Field(default="", validation_alias="SSH_AUTH_SOCK")
    credential_directory: Path | None = Field(default=None, validation_alias="CREDENTIALS_DIRECTORY")
    git_config_global: Path | None = None
    git_push_credential: Path | None = None

    def config_path(self, home: Path) -> Path:
        if self.config is not None:
            return self.config.expanduser().resolve()
        base = self.xdg_config_home if self.xdg_config_home is not None else home / ".config"
        return (base / "ocint" / "daemon.toml").resolve()


class LoadedDaemonConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    config: DaemonConfig
    settings: DaemonSettings


def load_daemon_config(settings: DaemonSettings, home: Path) -> LoadedDaemonConfig:
    path = settings.config_path(home)
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    return LoadedDaemonConfig(path=path, config=DaemonConfig.model_validate(raw), settings=settings)
