from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from ocint.daemon.models import GitHubLogin


class GitHubUser(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    login: GitHubLogin


class GitHubRepositoryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    github_repository: str
    actors: frozenset[GitHubLogin] = frozenset()


class GitHubRepositoryPolicies(RootModel[list[GitHubRepositoryPolicy]]):
    model_config = ConfigDict(frozen=True)


class GitHubPullReference(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    url: str = ""


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: int
    number: int
    title: str
    body: str = ""
    created_at: str
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


class GitHubIssues(RootModel[list[GitHubIssue]]):
    model_config = ConfigDict(frozen=True)


class GitHubComments(RootModel[list[GitHubComment]]):
    model_config = ConfigDict(frozen=True)


class GitHubPullRequests(RootModel[list[GitHubPullRequest]]):
    model_config = ConfigDict(frozen=True)


class GitHubIssueIds(RootModel[list[int]]):
    model_config = ConfigDict(frozen=True)


class StoredIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    root_source_id: str
    configured_repository: str
    github_repository: str
    github_issue_id: int
    issue_number: int
    eligible: bool
    pull_request_number: int
    pull_request_url: str


class StoredComment(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    issue_source_id: str
    github_comment_id: int
    marker: str


class CommentPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    comments: GitHubComments = Field(default_factory=lambda: GitHubComments(root=[]))
