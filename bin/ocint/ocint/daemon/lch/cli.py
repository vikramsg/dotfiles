import os
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

import click
from pydantic import BaseModel, ConfigDict, Field

from ocint._models import CliContext
from ocint.daemon.lch.systemd import CommandRunner, SubprocessRunner, SystemdLifecycle, SystemdPaths, installed_ocint


class OpenCodeProviderOptions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    base_url: str | None = Field(default=None, alias="baseURL")


class OpenCodeModelOptions(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    reasoning_effort: str | None = Field(default=None, alias="reasoningEffort")
    reasoning_summary: str | None = Field(default=None, alias="reasoningSummary")


class OpenCodeModalities(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    input: list[str] = Field(default_factory=list)
    output: list[str] = Field(default_factory=list)


class OpenCodeProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str
    name: str
    options: OpenCodeModelOptions = Field(default_factory=OpenCodeModelOptions)
    modalities: OpenCodeModalities = Field(default_factory=OpenCodeModalities)


class OpenCodeProvider(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    npm: str | None = None
    options: OpenCodeProviderOptions = Field(default_factory=OpenCodeProviderOptions)
    models: Mapping[str, OpenCodeProviderModel] = Field(default_factory=dict)


class OpenCodeSourceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    model: str
    provider: Mapping[str, OpenCodeProvider]


class OpenCodePermission(BaseModel):
    model_config = ConfigDict(frozen=True)
    read: str = "allow"
    edit: str = "allow"
    glob: str = "allow"
    grep: str = "allow"
    list: str = "allow"
    external_directory: Mapping[str, str]
    webfetch: str = "deny"
    websearch: str = "deny"
    bash: str = "deny"


class RestrictedOpenCodeConfig(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)
    schema_url: str = Field(validation_alias="$schema", serialization_alias="$schema")
    model: str
    provider: Mapping[str, OpenCodeProvider]
    share: str = "disabled"
    instructions: list[str] = Field(default_factory=list)
    plugin: list[str] = Field(default_factory=list)
    agent: Mapping[str, str] = Field(default_factory=dict)
    lsp: bool = False
    formatter: bool = False
    permission: OpenCodePermission


def restricted_opencode_config(source_path: Path, worktree_root: Path) -> str:
    source = OpenCodeSourceConfig.model_validate_json(source_path.read_text())
    provider_name, separator, model_name = source.model.partition("/")
    if not separator:
        raise click.ClickException("existing OpenCode model must include its provider")
    provider = source.provider.get(provider_name)
    if provider is None:
        raise click.ClickException(f"existing OpenCode provider is not configured: {provider_name}")
    model = provider.models.get(model_name)
    if model is None:
        raise click.ClickException(f"existing OpenCode model is not configured: {source.model}")
    restricted_provider = provider.model_copy(update={"models": {model_name: model}})
    restricted = RestrictedOpenCodeConfig(
        schema_url="https://opencode.ai/config.json",
        model=source.model,
        provider={provider_name: restricted_provider},
        permission=OpenCodePermission(external_directory={"*": "deny", f"{worktree_root.resolve()}/**": "allow"}),
    )
    return restricted.model_dump_json(by_alias=True, exclude_none=True, indent=2) + "\n"


def write_private_file(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def require_available_loopback_port(port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise click.ClickException(f"required private OpenCode port is unavailable: {port}") from error


def existing_github_token(runner: CommandRunner) -> str:
    token = runner.run(("gh", "auth", "token", "--hostname", "github.com")).stdout.strip()
    if not token:
        raise click.ClickException("existing gh auth did not return a GitHub token")
    return token


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
        raise click.ClickException(f"managed directory must be a user-owned regular directory: {path}")
    path.chmod(0o700)


def ensure_auth_symlink(source: Path, isolated_data_home: Path) -> Path:
    if (
        source.is_symlink()
        or not source.is_file()
        or source.stat().st_uid != os.getuid()
        or stat.S_IMODE(source.stat().st_mode) != 0o600
    ):
        raise click.ClickException(f"OpenCode auth must be a user-owned regular mode-0600 file: {source}")
    ensure_private_directory(isolated_data_home)
    auth_directory = isolated_data_home / "opencode"
    ensure_private_directory(auth_directory)
    target = auth_directory / "auth.json"
    if os.path.lexists(target):
        if not target.is_symlink() or target.lstat().st_uid != os.getuid() or target.resolve() != source.resolve():
            raise click.ClickException(f"managed OpenCode auth link is unsafe: {target}")
        return target
    temporary = auth_directory / f".auth.json.{secrets.token_hex(8)}"
    try:
        temporary.symlink_to(source.resolve())
        os.replace(temporary, target)
        directory_descriptor = os.open(auth_directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def lifecycle(home: Path) -> SystemdLifecycle:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return SystemdLifecycle(
        SystemdPaths(
            directory=config_home / "systemd" / "user",
            environment_file=config_home / "ocint" / "daemon.env",
            config_home=config_home,
            data_home=data_home,
            daemon_config=config_home / "ocint" / "daemon.toml",
            home=home,
        ),
        SubprocessRunner(),
    )


@click.group()
def lch() -> None:
    """Provision and operate the user systemd lifecycle."""


@lch.command("provision")
@click.pass_obj
def provision_command(context: CliContext) -> None:
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    state_home = Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state"))
    worktree_root = data_home / "ocint" / "worktrees"
    managed_lifecycle = lifecycle(home)
    managed_lifecycle.validate_host()
    ocint_executable = installed_ocint()
    managed_lifecycle.validate_executable(ocint_executable)
    managed_lifecycle.validate_lingering()
    opencode_executable = shutil.which("opencode")
    if opencode_executable is None:
        raise click.ClickException("opencode executable is not installed on PATH")
    opencode_version = subprocess.run(
        (opencode_executable, "--version"), check=True, capture_output=True, text=True
    ).stdout.strip()
    if opencode_version != "1.17.20":
        raise click.ClickException(f"opencode 1.17.20 is required; found {opencode_version}")
    require_available_loopback_port(4097)
    identity = home / ".ssh" / "id_ed25519"
    known_hosts = home / ".ssh" / "known_hosts"
    auth = data_home / "opencode" / "auth.json"
    opencode_config = config_home / "opencode" / "opencode.json"
    if (
        identity.is_symlink()
        or not identity.is_file()
        or identity.stat().st_uid != os.getuid()
        or stat.S_IMODE(identity.stat().st_mode) != 0o600
    ):
        path = identity
        raise click.ClickException(f"required credential must be user-owned mode 0600: {path}")
    if not auth.exists():
        raise click.ClickException(f"required OpenCode auth does not exist: {auth}")
    if not known_hosts.is_file() or not os.access(known_hosts, os.R_OK):
        raise click.ClickException(f"required known-hosts file is not readable: {known_hosts}")
    if not opencode_config.is_file():
        raise click.ClickException(f"required OpenCode config does not exist: {opencode_config}")
    restricted_payload = restricted_opencode_config(opencode_config, worktree_root)
    github_token = existing_github_token(managed_lifecycle.runner)
    directory = config_home / "ocint"
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise click.ClickException(f"configuration directory must not be a symlink: {directory}")
    directory.chmod(0o700)
    for path in (data_home / "ocint", state_home / "ocint"):
        ensure_private_directory(path)
    isolated_data_home = data_home / "ocint" / "opencode-data"
    ensure_auth_symlink(auth, isolated_data_home)
    environment = directory / "daemon.env"
    current_api_token = ""
    if environment.exists() and (
        environment.is_symlink()
        or not environment.is_file()
        or environment.stat().st_uid != os.getuid()
        or stat.S_IMODE(environment.stat().st_mode) != 0o600
    ):
        raise click.ClickException(f"existing environment file must be user-owned mode 0600: {environment}")
    if environment.exists():
        for line in environment.read_text().splitlines():
            if line.startswith("OCINT_DAEMON_API_TOKEN="):
                current_api_token = line.partition("=")[2]
    api_token = current_api_token or secrets.token_urlsafe(48)
    write_private_file(
        environment,
        f"OCINT_DAEMON_API_TOKEN={api_token}\nOCINT_DAEMON_GITHUB_TOKEN={github_token}\n",
    )
    isolated_config_home = directory / "opencode-xdg"
    isolated_config_directory = isolated_config_home / "opencode"
    ensure_private_directory(isolated_config_home)
    ensure_private_directory(isolated_config_directory)
    restricted = isolated_config_directory / "opencode.json"
    configuration = directory / "daemon.toml"
    for path in (restricted, configuration):
        if path.exists() and (path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid()):
            raise click.ClickException(f"managed configuration must be a user-owned regular file: {path}")
    write_private_file(restricted, restricted_payload)
    configuration_payload = f'''database_path = "{state_home / "ocint" / "daemon.sqlite"}"
mirror_root = "{data_home / "ocint" / "mirrors"}"
worktree_root = "{worktree_root}"
idle_timeout_seconds = 60

[[repositories]]
name = "dotfiles"
remote_url = "git@github.com:vikramsg/dotfiles.git"
default_branch = "main"
github_repository = "vikramsg/dotfiles"
author_name = "ocint daemon"
author_email = "ocint@example.invalid"
actors = ["vikramsg"]
checks = [["just", "--justfile", "bin/ocint/justfile", "check"], ["just", "--justfile", "bin/ocint/justfile", "test"]]

[opencode]
server_url = "http://127.0.0.1:4097"
username = "opencode"
expected_version = "1.17.20"
executable = "{opencode_executable}"
config_file = "{restricted}"
xdg_config_home = "{isolated_config_home}"
xdg_data_home = "{isolated_data_home}"
startup_timeout_seconds = 120

[github]
issue_label = "ocint"
agent_actor = "vikramsg"

[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "{identity}"
known_hosts_file = "{known_hosts}"
'''
    write_private_file(configuration, configuration_payload)
    managed_lifecycle.install(ocint_executable)
    context.output.write("ocint daemon provisioned; the systemd timer will start it", nl=True)


@lch.command("install")
def install_command() -> None:
    lifecycle(Path.home()).install(installed_ocint())


@lch.command("uninstall")
def uninstall_command() -> None:
    lifecycle(Path.home()).uninstall()


@lch.command("status")
@click.pass_obj
def status_command(context: CliContext) -> None:
    context.output.write(lifecycle(Path.home()).status(), nl=True)


@lch.command("logs")
@click.option("lines", "--lines", type=click.IntRange(min=1), default=100)
@click.option("follow", "--follow", is_flag=True)
@click.pass_obj
def logs_command(context: CliContext, lines: int, follow: bool) -> None:
    context.output.write(lifecycle(Path.home()).logs(lines, follow), nl=False)
