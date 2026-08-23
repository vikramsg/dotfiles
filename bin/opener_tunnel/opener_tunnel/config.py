import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when opener-tunnel configuration is missing or invalid."""


@dataclass(frozen=True)
class BrowserConfig:
    command: tuple[str, ...]


@dataclass(frozen=True)
class TmuxConfig:
    session: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class SshConfig:
    command: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class VmConfig:
    host: str
    socket_path: str


@dataclass(frozen=True)
class OpenerTunnelConfig:
    socket_path: Path
    browser: BrowserConfig
    tmux: TmuxConfig
    ssh: SshConfig
    vm: VmConfig


def get_config_file(config_file: Path | None = None) -> Path:
    if config_file is not None:
        return config_file.expanduser()
    configured_path = os.environ.get(
        "OPENER_TUNNEL_CONFIG_FILE", "~/.config/opener-tunnel/config.toml"
    )
    return Path(configured_path).expanduser()


def load_config(config_file: Path | None = None) -> OpenerTunnelConfig:
    path = get_config_file(config_file)
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    socket_path = Path(_required_string(data, "socket_path")).expanduser()
    browser = _required_table(data, "browser")
    tmux = _required_table(data, "tmux")
    ssh = _required_table(data, "ssh")
    vm = _required_table(data, "vm")
    return OpenerTunnelConfig(
        socket_path=socket_path,
        browser=BrowserConfig(
            command=_required_argv(browser, "command", setting="browser.command")
        ),
        tmux=TmuxConfig(
            session=_required_string(tmux, "session", setting="tmux.session"),
            command=_required_argv(tmux, "command", setting="tmux.command"),
        ),
        ssh=SshConfig(
            command=_required_string(ssh, "command", setting="ssh.command"),
            args=_required_argv(ssh, "args", setting="ssh.args", allow_empty=True),
        ),
        vm=VmConfig(
            host=_required_string(vm, "host", setting="vm.host"),
            socket_path=_required_string(vm, "socket_path", setting="vm.socket_path"),
        ),
    )


def build_ssh_argv(config: OpenerTunnelConfig) -> list[str]:
    # The Python config layer assembles:
    #   ssh command
    #     + ssh args
    #     + ["-R", "<vm.socket_path>:<local socket_path>"]
    #     + [vm.host]
    return [
        config.ssh.command,
        *config.ssh.args,
        "-R",
        f"{config.vm.socket_path}:{config.socket_path}",
        config.vm.host,
    ]


def _required_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a TOML table")
    return value


def _required_string(
    data: dict[str, Any], key: str, *, setting: str | None = None
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{setting or key} must be a non-empty string")
    return value


def _required_argv(
    data: dict[str, Any],
    key: str,
    *,
    setting: str | None = None,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    value = data.get(key)
    setting_name = setting or key
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "an array" if allow_empty else "a non-empty array"
        raise ConfigError(f"{setting_name} must be {qualifier} of strings")
    if any(not isinstance(argument, str) or not argument for argument in value):
        raise ConfigError(f"{setting_name} must contain only non-empty strings")
    return tuple(value)
