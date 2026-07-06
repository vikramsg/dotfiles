from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolvedPaths(OutputModel):
    config_path: Path
    db_path: Path
    config_exists: bool
    db_exists: bool


class CliProgress(Protocol):
    def update(self, message: str, *, current: int | None = None, total: int | None = None) -> None: ...


class CliOutput(Protocol):
    def write(self, text: str, *, stderr: bool = False, nl: bool = False, enabled: bool = True) -> None: ...

    def progress(self, message: str, *, enabled: bool = True) -> AbstractContextManager[CliProgress]: ...


@dataclass(frozen=True)
class CliContext:
    output: CliOutput
