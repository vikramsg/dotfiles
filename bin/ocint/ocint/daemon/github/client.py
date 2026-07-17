from collections.abc import AsyncIterator

import aiohttp
from pydantic import TypeAdapter

from ocint.daemon.github.models import GitHubComment, GitHubIssue, GitHubPullRequest


class GitHubClient:
    def __init__(self, api_url: str, token: str) -> None:
        self.api_url = api_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.client: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self.client = aiohttp.ClientSession(headers=self.headers)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def issues(self, repository: str, label: str) -> tuple[GitHubIssue, ...]:
        values: list[GitHubIssue] = []
        async for payload in self._pages(f"/repos/{repository}/issues", {"state": "open", "labels": label}):
            for item in TypeAdapter(tuple[GitHubIssue, ...]).validate_python(payload):
                if item.pull_request is None:
                    values.append(item)
        return tuple(values)

    async def comments(self, repository: str, number: int) -> tuple[GitHubComment, ...]:
        values: list[GitHubComment] = []
        async for payload in self._pages(f"/repos/{repository}/issues/{number}/comments"):
            values.extend(TypeAdapter(tuple[GitHubComment, ...]).validate_python(payload))
        return tuple(values)

    async def pull_request(self, repository: str, number: int) -> GitHubPullRequest:
        async with self._session().get(f"{self.api_url}/repos/{repository}/pulls/{number}") as response:
            response.raise_for_status()
            return GitHubPullRequest.model_validate(await response.json())

    async def create_pull_request(
        self, repository: str, branch: str, base: str, title: str, body: str
    ) -> GitHubPullRequest:
        async with self._session().post(
            f"{self.api_url}/repos/{repository}/pulls",
            json={"head": branch, "base": base, "title": title, "body": body},
        ) as response:
            response.raise_for_status()
            return GitHubPullRequest.model_validate(await response.json())

    async def find_pull_request(self, repository: str, branch: str, base: str) -> GitHubPullRequest | None:
        owner = repository.split("/", maxsplit=1)[0]
        async with self._session().get(
            f"{self.api_url}/repos/{repository}/pulls",
            params={"state": "open", "head": f"{owner}:{branch}", "base": base},
        ) as response:
            response.raise_for_status()
            pulls = TypeAdapter(list[GitHubPullRequest]).validate_python(await response.json())
        return pulls[0] if pulls else None

    async def post_comment(self, repository: str, number: int, body: str) -> GitHubComment:
        async with self._session().post(
            f"{self.api_url}/repos/{repository}/issues/{number}/comments", json={"body": body}
        ) as response:
            response.raise_for_status()
            return GitHubComment.model_validate(await response.json())

    async def _pages(self, path: str, params: dict[str, str] | None = None) -> AsyncIterator[list[dict[str, str]]]:
        url = f"{self.api_url}{path}"
        query = {**(params or {}), "per_page": "100"}
        while url:
            async with self._session().get(url, params=query) as response:
                response.raise_for_status()
                yield await response.json()
                url = response.links.get("next", {}).get("url", "")
                query = {}

    def _session(self) -> aiohttp.ClientSession:
        if self.client is None or self.client.closed:
            raise RuntimeError("GitHub client is not started")
        return self.client
