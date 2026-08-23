import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


DEFAULT_NAMESPACE = "com.vikramsg.dotfiles"


@dataclass(frozen=True)
class LchConfig:
    namespace: str
    services: dict[str, tuple[str, ...]]


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
    raw_services = data.get("services", {})
    if not isinstance(raw_services, dict):
        raise ValueError("services must be a TOML table")
    services: dict[str, tuple[str, ...]] = {}
    for service_id, raw_service in raw_services.items():
        if not isinstance(raw_service, dict):
            raise ValueError(f"services.{service_id} must be a TOML table")
        command = raw_service.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(argument, str) or not argument for argument in command)
        ):
            raise ValueError(
                f"services.{service_id}.command must be a non-empty array of strings"
            )
        services[service_id] = tuple(command)
    namespace = data.get("namespace", DEFAULT_NAMESPACE)
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("namespace must be a non-empty string")
    return LchConfig(namespace=namespace, services=services)
