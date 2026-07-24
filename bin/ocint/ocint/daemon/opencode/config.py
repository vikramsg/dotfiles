from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class OpenCodeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_url: HttpUrl = HttpUrl("http://127.0.0.1:4097")
    username: str = "opencode"
    request_timeout_seconds: int = Field(default=30, ge=1)
    expected_version: Literal["1.17.20"] = "1.17.20"
    executable: Path = Path("/usr/bin/opencode")
    config_file: Path
    xdg_config_home: Path
    xdg_data_home: Path
    startup_timeout_seconds: int = Field(default=120, ge=1)
    shutdown_timeout_seconds: int = Field(default=10, ge=1)

    @field_validator("executable", "config_file", "xdg_config_home", "xdg_data_home")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class OpenCodeRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: OpenCodeConfig
    password: str
    execution_timeout_seconds: int
    process_path: str
    process_lang: str
