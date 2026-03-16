import json
import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_NAMESPACE = "com.vikramsg.dotfiles"


@dataclass(frozen=True)
class LchConfig:
    namespace: str


def _expand_path(raw_path: str | Path) -> Path:
    return Path(raw_path).expanduser()


def get_default_config_file() -> Path:
    return _expand_path("~/.config/lch/config.json")


def get_config_file(config_file: Path | None = None) -> Path:
    if config_file is not None:
        return _expand_path(config_file)
    return _expand_path(os.environ.get("LCH_CONFIG_FILE", get_default_config_file()))


def load_config(config_file: Path | None = None) -> LchConfig:
    resolved_config_file = get_config_file(config_file)
    data = json.loads(resolved_config_file.read_text()) if resolved_config_file.exists() else {}
    return LchConfig(namespace=data.get("namespace", DEFAULT_NAMESPACE))
