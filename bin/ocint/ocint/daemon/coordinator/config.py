from ipaddress import ip_address
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ocint.daemon.opencode import OpenCodeConfig


class RepositoryCatalogueEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    github_repository: str = Field(min_length=1)
    default_branch: str = Field(min_length=1)

    @field_validator("name", "description", "github_repository", "default_branch")
    @classmethod
    def reject_blank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("repository catalogue metadata must not be blank")
        return value


class CoordinatorWorkspaceConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path
    repositories: tuple[RepositoryCatalogueEntry, ...]

    @model_validator(mode="after")
    def unique_repository_names(self) -> CoordinatorWorkspaceConfig:
        names = [repository.name for repository in self.repositories]
        if len(names) != len(set(names)):
            raise ValueError("coordinator repository names must be unique")
        return self


class CoordinatorIngressConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8_733, ge=1, le=65_535)
    max_request_bytes: int = Field(default=65_536, gt=0)
    timestamp_tolerance_seconds: int = Field(default=300, gt=0)
    processing_timeout_seconds: float = Field(default=2.5, gt=0, lt=3)
    database_busy_timeout_ms: int = Field(default=2_000, gt=0)

    @field_validator("host")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        try:
            loopback = ip_address(value).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValueError("coordinator ingress host must be a loopback IP address")
        return value

    @model_validator(mode="after")
    def require_database_timeout_within_processing_budget(self) -> CoordinatorIngressConfig:
        if self.database_busy_timeout_ms > self.processing_timeout_seconds * 1_000:
            raise ValueError("database busy timeout must not exceed the ingress processing timeout")
        return self


class CoordinatorSlackChannelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_id: str = Field(min_length=1)
    authorized_users: frozenset[str] = Field(min_length=1)

    @field_validator("channel_id")
    @classmethod
    def reject_blank_channel(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Slack channel ID must not be blank")
        return value

    @field_validator("authorized_users")
    @classmethod
    def reject_blank_users(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not user.strip() for user in value):
            raise ValueError("Slack authorized user IDs must not be blank")
        return value


class CoordinatorSlackConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: str = Field(min_length=1)
    channels: tuple[CoordinatorSlackChannelConfig, ...] = Field(min_length=1)

    @field_validator("workspace_id")
    @classmethod
    def reject_blank_workspace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Slack workspace ID must not be blank")
        return value

    @model_validator(mode="after")
    def unique_channels(self) -> CoordinatorSlackConfig:
        identifiers = [channel.channel_id for channel in self.channels]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("coordinator Slack channel IDs must be unique")
        return self

    @property
    def required_scopes(self) -> frozenset[str]:
        return frozenset(("channels:history", "chat:write"))


class CoordinatorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_root: Path
    turn_timeout_seconds: int = Field(gt=0)
    shutdown_timeout_seconds: int = Field(gt=0)
    orphan_retention_seconds: int = Field(gt=0)
    retry_seconds: int = Field(gt=0)
    max_turn_retries: int = Field(default=3, gt=0)
    response_chunk_characters: int = Field(gt=16, le=3_500)
    slack_post_interval_seconds: float = Field(gt=0)
    safe_failure_text: str = Field(
        default="The coordinator could not complete this request. Please try again.", min_length=1
    )
    ingress: CoordinatorIngressConfig
    slack: CoordinatorSlackConfig
    opencode: OpenCodeConfig

    @field_validator("workspace_root")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().absolute()
