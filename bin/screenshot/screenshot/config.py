import os
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_CLIPBOARD_HISTORY_LIMIT = 5
DEFAULT_FILENAME_PATTERNS = (
    "Screenshot *.png",
    "Screen Shot *.png",
)
DEFAULT_SCREENSHOT_DIR = "~/Desktop/Screenshots"


def _expand_path(raw_path: str | Path) -> Path:
    return Path(raw_path).expanduser()


def get_default_screenshot_dir() -> Path:
    return _expand_path(DEFAULT_SCREENSHOT_DIR)


NonEmptyString = Annotated[str, Field(min_length=1)]


class SyncSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyString
    local_dir: Path
    vm_host: NonEmptyString
    remote_dir: NonEmptyString
    include: tuple[NonEmptyString, ...] = Field(min_length=1)
    exclude: tuple[NonEmptyString, ...] = ()

    @field_validator("local_dir")
    @classmethod
    def expand_local_directory(cls, value: Path) -> Path:
        return value.expanduser()


class SyncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sources: tuple[SyncSource, ...] = ()

    @model_validator(mode="after")
    def require_unique_source_ids(self) -> "SyncConfig":
        if len({source.id for source in self.sources}) != len(self.sources):
            raise ValueError("sync source ids must be unique")
        return self


class ScreenshotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    screenshot_dir: Path = Field(default_factory=get_default_screenshot_dir)
    clipboard_history_limit: int = Field(default=DEFAULT_CLIPBOARD_HISTORY_LIMIT, ge=1)
    filename_patterns: tuple[NonEmptyString, ...] = DEFAULT_FILENAME_PATTERNS
    sync: SyncConfig = SyncConfig()

    @field_validator("screenshot_dir")
    @classmethod
    def expand_screenshot_directory(cls, value: Path) -> Path:
        return value.expanduser()


def get_default_config_file() -> Path:
    return _expand_path("~/.config/screenshot/config.json")


def get_config_file(config_file: Path | None = None) -> Path:
    if config_file is not None:
        return _expand_path(config_file)
    return _expand_path(os.environ.get("SCREENSHOT_CONFIG_FILE", get_default_config_file()))


def load_config(config_file: Path | None = None) -> ScreenshotConfig:
    resolved_config_file = get_config_file(config_file)
    config = ScreenshotConfig.model_validate_json(
        resolved_config_file.read_text() if resolved_config_file.exists() else "{}"
    )
    if override := os.environ.get("SCREENSHOT_DIR"):
        return config.model_copy(update={"screenshot_dir": _expand_path(override)})
    return config
