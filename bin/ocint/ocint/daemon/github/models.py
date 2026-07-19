from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    thread_id: int
    github_repository: str
    github_issue_id: int
    issue_number: int
    pull_request_number: int
    pull_request_url: str


class StoredComment(BaseModel):
    model_config = ConfigDict(frozen=True)

    github_comment_id: int
    message_id: int
    marker: str


class CommentPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    comments: tuple[GitHubComment, ...] = Field(default_factory=tuple)
