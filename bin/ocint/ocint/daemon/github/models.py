from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class CommentState(StrEnum):
    PENDING = "pending"
    BATCHED = "batched"
    ADDRESSED = "addressed"
    REJECTED = "rejected"
    ERRORED = "errored"
    IGNORED = "ignored"


class GitHubUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    login: str


class GitHubPullReference(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    url: str = ""


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int
    number: int
    title: str
    body: str = ""
    user: GitHubUser
    pull_request: GitHubPullReference | None = None

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: str | None) -> str:
        return value or ""


class GitHubComment(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int
    body: str
    user: GitHubUser
    created_at: str

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: str | None) -> str:
        return value or ""


class GitHubPullRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    number: int
    html_url: str
    state: str
    merged: bool = False


class StoredIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    repository: str
    github_repository: str
    github_issue_id: int
    issue_number: int
    issue_author: str
    title: str
    body: str
    job_id: str
    pull_request_number: int
    pull_request_url: str
    initial_state: str
    active_anchor_comment_id: int
    error: str


class StoredComment(BaseModel):
    model_config = ConfigDict(frozen=True)
    github_comment_id: int
    issue_id: int
    body: str
    actor_login: str
    actor_type: ActorType
    state: CommentState
    github_created_at: str
    marker: str
    agent_response_comment_id: int


class CommentPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    comments: tuple[GitHubComment, ...] = Field(default_factory=tuple)
