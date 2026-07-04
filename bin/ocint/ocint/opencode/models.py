from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ocint.opencode.schema import PATH_ARRAY_KEYS, PATH_VALUE_KEYS


class OpenCodeJsonModel(BaseModel):
    # OpenCode payloads evolve independently of this tool. Extra fields stay
    # available through model_dump while typed aliases cover fields we depend on.
    model_config = ConfigDict(extra="allow", populate_by_name=True, frozen=True)


class OpenCodeCacheTokens(OpenCodeJsonModel):
    read: int = 0
    write: int = 0


class OpenCodeTokenPayload(OpenCodeJsonModel):
    input: int = 0
    output: int = 0
    reasoning: int = 0
    total: int | None = None
    cache: OpenCodeCacheTokens = Field(default_factory=OpenCodeCacheTokens)


class OpenCodeMessageData(OpenCodeJsonModel):
    role: str | None = None
    provider_id: str | None = Field(default=None, alias="providerID")
    model_id: str | None = Field(default=None, alias="modelID")
    text: str | None = None
    content: str | None = None


class OpenCodePartData(OpenCodeJsonModel):
    type: str | None = None
    text: str | None = None
    content: str | None = None
    cost: float | None = None
    tokens: OpenCodeTokenPayload = Field(default_factory=OpenCodeTokenPayload)
    path: str | None = None
    file: str | None = None
    file_path: str | None = Field(default=None, alias="filePath")


class OpenCodeEventData(OpenCodeJsonModel):
    type: str | None = None
    text: str | None = None
    message: str | None = None
    title: str | None = None
    path: str | None = None
    file: str | None = None
    file_path: str | None = Field(default=None, alias="filePath")


class OpenCodeSessionData(OpenCodeJsonModel):
    title: str | None = None
    directory: str | None = None
    workspace: str | None = None
    cwd: str | None = None
    path: str | None = None


class StorageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OpenCodeSessionRow(StorageModel):
    id: str
    parent_id: str | None = None
    title: str | None = None
    cwd: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    data: OpenCodeSessionData = Field(default_factory=OpenCodeSessionData)


class OpenCodeMessageRow(StorageModel):
    id: str
    session_id: str | None = None
    time_created: int | None = None
    data: OpenCodeMessageData = Field(default_factory=OpenCodeMessageData)


class OpenCodePartRow(StorageModel):
    id: str
    message_id: str | None = None
    session_id: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    data: OpenCodePartData = Field(default_factory=OpenCodePartData)


class OpenCodeEventRow(StorageModel):
    id: str
    session_id: str | None = None
    event_type: str = "event"
    time_created: int | None = None
    time_updated: int | None = None
    data: OpenCodeEventData = Field(default_factory=OpenCodeEventData)


class OpenCodeUnifiedEventRow(StorageModel):
    id: str
    source_table: Literal["event", "part", "message"]
    session_id: str | None = None
    message_id: str | None = None
    time_created: int | None = None
    time_updated: int | None = None
    event_type: str
    data: OpenCodeJsonModel
    source_path: str | None = None


def payload_to_text(payload: OpenCodeJsonModel) -> str:
    return " ".join(_string_values(payload.model_dump(mode="json", by_alias=True, exclude_none=True)))


def payload_paths(payload: OpenCodeJsonModel) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    _collect_paths(payload.model_dump(mode="json", by_alias=True, exclude_none=True), paths, seen)
    return paths


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_string_values(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_string_values(item))
        return values
    if value is None:
        return []
    return [str(value)]


def _collect_paths(
    value: Any, paths: list[str], seen: set[str], *, key: str | None = None, in_path_array: bool = False
) -> None:
    if isinstance(value, dict):
        for nested_key, item in value.items():
            _collect_paths(item, paths, seen, key=nested_key)
        return
    if isinstance(value, list):
        array_context = in_path_array or key in PATH_ARRAY_KEYS
        for item in value:
            _collect_paths(item, paths, seen, key=key, in_path_array=array_context)
        return
    if isinstance(value, str) and (key in PATH_VALUE_KEYS or in_path_array) and value not in seen:
        seen.add(value)
        paths.append(value)
