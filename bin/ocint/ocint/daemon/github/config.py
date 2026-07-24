from pydantic import BaseModel, ConfigDict, HttpUrl

from ocint.daemon.models import GitHubLogin


class GitHubConfig(BaseModel):
    """Configuration settings for GitHub polling and agent identity.

    Defines the target GitHub API URL, the issue label to monitor, and the
    actor username used by the automated agent.
    """

    model_config = ConfigDict(frozen=True)

    api_url: HttpUrl = HttpUrl("https://api.github.com")
    issue_label: str = "ocint"
    agent_actor: GitHubLogin
