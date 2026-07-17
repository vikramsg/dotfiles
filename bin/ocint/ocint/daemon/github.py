import aiohttp
from pydantic import BaseModel, ConfigDict, TypeAdapter


class PullRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    html_url: str


class GitHubClient:
    def __init__(self, api_url: str, token: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.token = token

    async def publish(self, repository: str, branch: str, base: str, title: str, body: str) -> str:
        owner = repository.split("/", maxsplit=1)[0]
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get(
                f"{self.api_url}/repos/{repository}/pulls",
                params={"state": "open", "head": f"{owner}:{branch}", "base": base},
            ) as response:
                response.raise_for_status()
                pulls = TypeAdapter(tuple[PullRequest, ...]).validate_python(await response.json())
            if pulls:
                return pulls[0].html_url
            async with client.post(
                f"{self.api_url}/repos/{repository}/pulls",
                json={"head": branch, "base": base, "title": title, "body": body},
            ) as response:
                response.raise_for_status()
                return PullRequest.model_validate(await response.json()).html_url
