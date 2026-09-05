"""Local service discovery and authenticated HTTP; no service lifecycle changes."""

from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, ValidationError, field_validator

from ocost.models import Project, StatsResponse
from ocost.window import Window


class APIError(Exception):
    """A safe, user-facing connection or API error."""


class Connection(BaseModel):
    model_config = ConfigDict(strict=True)
    url: str
    password: SecretStr = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def local_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "::1", "localhost"}
            or url.port is None
            or url.username is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("expected a local HTTP service URL")
        return value.rstrip("/")

    @classmethod
    def discover(cls, registration: Path) -> Connection:
        try:
            return cls.model_validate_json(registration.read_bytes())
        except OSError:
            raise APIError("Cannot read OpenCode service registration. Start OpenCode V2, then retry.") from None
        except ValidationError:
            # Never include Pydantic's input values: this file contains a password.
            raise APIError("Invalid local OpenCode service registration. Check `opencode2 service status`.") from None

    def client(self, *, transport: httpx2.BaseTransport | None = None) -> httpx2.Client:
        return httpx2.Client(
            base_url=self.url,
            auth=httpx2.BasicAuth("opencode", self.password.get_secret_value()),
            timeout=httpx2.Timeout(30, connect=5),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )


class API:
    def __init__(self, client: httpx2.Client) -> None:
        self.client = client

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> httpx2.Response:
        try:
            response = self.client.get(path, params=params)
            response.raise_for_status()
            return response
        except httpx2.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                raise APIError("OpenCode authentication failed. Check `opencode2 service status`.") from None
            raise APIError(f"OpenCode returned HTTP {status} for {path}.") from None
        except httpx2.TimeoutException:
            raise APIError(f"OpenCode request timed out for {path}; retry when the service is responsive.") from None
        except httpx2.RequestError:
            raise APIError("Cannot reach OpenCode. Check `opencode2 service status`.") from None

    def projects(self) -> list[Project]:
        response = self._get("/api/project")
        try:
            projects = TypeAdapter(list[Project]).validate_json(response.content)
        except ValidationError:
            raise APIError("Invalid OpenCode project response.") from None
        if len({project.id for project in projects}) != len(projects):
            raise APIError("OpenCode returned duplicate project IDs.")
        return projects

    def stats(self, window: Window, *, project: str | None = None) -> StatsResponse:
        params = window.params()
        if project is not None:
            params["project"] = project
        response = self._get("/api/session/stats", params=params)
        try:
            usage = StatsResponse.model_validate_json(response.content)
        except ValidationError:
            raise APIError("Invalid OpenCode usage statistics response.") from None
        if usage.data.range.start != window.start_ms or usage.data.range.to != window.end_ms:
            raise APIError("OpenCode returned usage for a different time range.")
        return usage
