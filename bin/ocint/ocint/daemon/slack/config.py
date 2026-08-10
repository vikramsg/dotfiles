from pydantic import BaseModel, ConfigDict, Field, model_validator


class SlackChannelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    channel_id: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    authorized_users: frozenset[str] = Field(min_length=1)
    initial_oldest: str = Field(min_length=1, pattern=r"^[0-9]+\.[0-9]+$")


class SlackConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_id: str = Field(min_length=1)
    completion_reaction: str = Field(default="white_check_mark", min_length=1)
    channels: tuple[SlackChannelConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_channels(self) -> SlackConfig:
        identifiers = [channel.channel_id for channel in self.channels]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Slack channel IDs must be unique")
        return self

    @property
    def required_scopes(self) -> frozenset[str]:
        return frozenset(("channels:history", "chat:write", "reactions:write"))


class SlackIngressConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_request_bytes: int = Field(default=65_536, gt=0)
    timestamp_tolerance_seconds: int = Field(default=300, gt=0)
