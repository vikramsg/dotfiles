from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator


class GitConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    ssh_executable: Path
    identity_file: Path
    known_hosts_file: Path

    @field_validator("ssh_executable", "identity_file", "known_hosts_file")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class GitRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    mirror_root: Path
    worktree_root: Path
    validation_environment: Mapping[str, str]
    git_environment: Mapping[str, str]
    transport: GitConfig
    timeout_seconds: int
    output_bytes: int
