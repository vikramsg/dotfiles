import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_NAMESPACE = "com.vikramsg.dotfiles"
NonEmptyString = Annotated[str, Field(min_length=1)]


class CommandService(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command: tuple[NonEmptyString, ...] = Field(min_length=1)


class ApplicationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path

    @field_validator("path", mode="before")
    @classmethod
    def expand_application_path(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)) or not str(value):
            raise ValueError("application path must not be empty")
        return Path(value).expanduser()


class MacOSApplication(ApplicationDefinition):
    type: Literal["macos"]


class LinuxApplication(ApplicationDefinition):
    """Reserved configuration shape; Linux application launch is not implemented."""

    type: Literal["linux"]


Application = Annotated[
    MacOSApplication | LinuxApplication,
    Field(discriminator="type"),
]


class ApplicationService(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    application: Application


Service = CommandService | ApplicationService


class LchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    namespace: NonEmptyString = DEFAULT_NAMESPACE
    services: dict[str, Service] = Field(default_factory=dict)


def _expand_path(raw_path: str | Path) -> Path:
    return Path(raw_path).expanduser()


def get_default_config_file() -> Path:
    return _expand_path("~/.config/lch/config.toml")


def get_config_file(config_file: Path | None = None) -> Path:
    if config_file is not None:
        return _expand_path(config_file)
    return _expand_path(os.environ.get("LCH_CONFIG_FILE", get_default_config_file()))


def load_config(config_file: Path | None = None) -> LchConfig:
    resolved_config_file = get_config_file(config_file)
    data = tomllib.loads(resolved_config_file.read_text()) if resolved_config_file.exists() else {}
    return LchConfig.model_validate(data)
