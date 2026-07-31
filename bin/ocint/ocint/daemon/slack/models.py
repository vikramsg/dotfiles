from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


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
