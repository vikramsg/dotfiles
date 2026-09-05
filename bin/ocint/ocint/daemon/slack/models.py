from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


def parse_slack_timestamp(timestamp: str) -> int:
    seconds, separator, fraction = timestamp.partition(".")
    if separator != "." or not seconds.isdigit() or len(fraction) != 6 or not fraction.isdigit():
        raise ValueError(f"invalid Slack timestamp: {timestamp!r}")
    return int(seconds) * 1_000_000 + int(fraction)


class SlackMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    ts: str = Field(min_length=1)
    text: str = ""
    user: str = ""
    bot_id: str = ""
    thread_ts: str = ""
    client_msg_id: str = ""


class SlackMessages(RootModel[list[SlackMessage]]):
    model_config = ConfigDict(frozen=True)


class SlackAuth(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    user_id: str = Field(min_length=1)
    bot_id: str = ""
    team_id: str = Field(min_length=1)


class SlackResponseMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    next_cursor: str = ""

    @field_validator("next_cursor", mode="before")
    @classmethod
    def normalize_cursor(cls, value: str | None) -> str:
        return value or ""


class SlackHistory(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    messages: SlackMessages = Field(default_factory=lambda: SlackMessages(root=[]))
    response_metadata: SlackResponseMetadata = Field(default_factory=SlackResponseMetadata)


class SlackPostedMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    ts: str = Field(min_length=1)


class SlackFile(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1)


class SlackBotProfile(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = ""


class SlackEventPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str = Field(min_length=1)
    channel: str = ""
    channel_type: str = ""
    user: str = ""
    bot_id: str = ""
    app_id: str = ""
    text: str = ""
    ts: str = ""
    event_ts: str = ""
    thread_ts: str = ""
    subtype: str = ""
    client_msg_id: str = ""
    files: tuple[SlackFile, ...] = ()
    bot_profile: SlackBotProfile | None = None


class SlackPublicChannelMessage(SlackEventPayload):
    channel_type: Literal["channel"]


class SlackPrivateChannelMessage(SlackEventPayload):
    # FIXME: message.groups/groups:history deployment is not implemented.
    channel_type: Literal["group"]


type SlackChannelMessage = SlackPublicChannelMessage | SlackPrivateChannelMessage
type SlackEvent = SlackChannelMessage | SlackEventPayload


class SlackEventCallback(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: Literal["event_callback"] = "event_callback"
    team_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    event_time: int = Field(ge=0)
    event: SlackEvent


class SlackUrlVerification(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: Literal["url_verification"] = "url_verification"
    team_id: str = Field(min_length=1)
    challenge: str = Field(min_length=1)


type SlackEventsEnvelope = SlackEventCallback | SlackUrlVerification


class StoredSlackThread(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel_id: str
    root_ts: str
    workspace_id: str
    logical_source_id: str
    root_identity: str
    configured_repository: str
    title: str
    authorized: bool
    closed: bool
    reopen_root: bool = False


class SlackRootReference(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel_id: str
    root_ts: str
