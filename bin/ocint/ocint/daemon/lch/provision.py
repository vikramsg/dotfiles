import json
import os
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

import click
from pydantic import BaseModel, ConfigDict, Field

from ocint.daemon.config import (
    DaemonConfig,
    DaemonContext,
    GitConfig,
    GitHubConfig,
    LifecycleConfig,
    LoggingConfig,
    OpenCodeConfig,
    RepositoryConfig,
)
from ocint.daemon.lch.systemd import CommandRunner, SystemdLifecycle, installed_ocint


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
    read: str
    edit: str
    glob: str
    grep: str
    list: str
    external_directory: Mapping[str, str]
    webfetch: str
    websearch: str
    bash: str


class StaticOpenCodePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")
    schema_url: str = Field(validation_alias="$schema", serialization_alias="$schema")
    share: str
    instructions: list[str]
    plugin: list[str]
    agent: Mapping[str, str]
    lsp: bool
    formatter: bool
    permission: OpenCodePermission


class RestrictedOpenCodeConfig(StaticOpenCodePolicy):
    model: str
    provider: Mapping[str, OpenCodeProvider]


class GitHubUser(BaseModel):
    model_config = ConfigDict(frozen=True)
    login: str


class GitHubBranch(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str


class GitHubView(BaseModel):
    model_config = ConfigDict(frozen=True)
    name_with_owner: str = Field(alias="nameWithOwner")
    default_branch_ref: GitHubBranch = Field(alias="defaultBranchRef")


class GitIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    email: str


class SshDiscovery(BaseModel):
    model_config = ConfigDict(frozen=True)
    executable: Path
    identity_file: Path
    known_hosts_file: Path


class SshDestination(BaseModel):
    model_config = ConfigDict(frozen=True)
    host: str
    user: str | None = None
    port: int | None = None


class OpenCodeDiscovery(BaseModel):
    model_config = ConfigDict(frozen=True)
    executable: Path
    version: str
    source_config: Path
    auth_source: Path
    model: str
    provider_name: str
    provider: OpenCodeProvider


class ProvisionPaths(BaseModel):
    model_config = ConfigDict(frozen=True)
    home: Path
    config_home: Path
    data_home: Path
    state_home: Path
    worktree_root: Path
    isolated_config_home: Path
    isolated_data_home: Path
    environment: Path
    configuration: Path
    effective_opencode_config: Path


class ProvisionDiscovery(BaseModel):
    model_config = ConfigDict(frozen=True)
    checkout: Path
    login: str
    github_repository: str
    default_branch: str
    github_token: str
    remote_url: str
    author: GitIdentity
    ssh: SshDiscovery
    opencode: OpenCodeDiscovery
    policy: StaticOpenCodePolicy
    policy_bytes: bytes
    effective_opencode_payload: str
    paths: ProvisionPaths
    ocint_executable: Path


def policy_bytes() -> bytes:
    resource = files("ocint.daemon").joinpath("opencode.daemon.json")
    if not resource.is_file():
        raise click.ClickException(f"packaged OpenCode policy resource is missing: {resource}")
    return resource.read_bytes()


def policy_resource_path() -> str:
    return str(files("ocint.daemon").joinpath("opencode.daemon.json"))


def load_policy() -> tuple[StaticOpenCodePolicy, bytes]:
    payload = policy_bytes()
    policy = StaticOpenCodePolicy.model_validate_json(payload)
    if policy.permission.external_directory != {"*": "deny"}:
        raise click.ClickException("packaged OpenCode policy must contain only the static external-directory deny rule")
    return policy, payload


def restricted_opencode_config(
    policy: StaticOpenCodePolicy,
    model_name_with_provider: str,
    provider_name: str,
    provider: OpenCodeProvider,
    worktree_root: Path,
) -> str:
    if not model_name_with_provider.startswith(f"{provider_name}/"):
        raise click.ClickException("selected OpenCode model does not match its provider")
    model_name = model_name_with_provider.removeprefix(f"{provider_name}/")
    model = provider.models.get(model_name)
    if model is None:
        raise click.ClickException(f"existing OpenCode model is not configured: {model_name_with_provider}")
    restricted_provider = provider.model_copy(update={"models": {model_name: model}})
    permission = policy.permission.model_copy(
        update={"external_directory": {"*": "deny", f"{worktree_root.resolve()}/**": "allow"}}
    )
    restricted = RestrictedOpenCodeConfig(
        **policy.model_dump(by_alias=False, exclude={"permission"}),
        model=model_name_with_provider,
        provider={provider_name: restricted_provider},
        permission=permission,
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
        raise click.ClickException(f"required loopback port is unavailable: {port}") from error


def existing_github_token(runner: CommandRunner, environment: Mapping[str, str]) -> str:
    token = runner.run_isolated(("gh", "auth", "token", "--hostname", "github.com"), environment).stdout.strip()
    if not token:
        raise click.ClickException("existing gh auth did not return a GitHub token")
    return token


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
        raise click.ClickException(f"managed directory must be a user-owned regular directory: {path}")
    path.chmod(0o700)


def ensure_auth_symlink(source: Path, isolated_data_home: Path) -> Path:
    if source.is_symlink() or not _user_file(source, 0o600):
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
    finally:
        temporary.unlink(missing_ok=True)
    return target


def discover(
    runner: CommandRunner, lifecycle: SystemdLifecycle, checkout: Path, context: DaemonContext
) -> ProvisionDiscovery:
    home = context.home
    if context.environment.get("GIT_SSH_COMMAND") or context.environment.get("GIT_SSH"):
        raise click.ClickException("unset GIT_SSH_COMMAND and GIT_SSH before provisioning")
    git_environment = discovery_environment(context, False)
    gh_environment = discovery_environment(context, True)
    root = Path(
        runner.run_isolated(
            ("git", "-C", str(checkout), "rev-parse", "--show-toplevel"), git_environment
        ).stdout.strip()
    ).resolve()
    if root != checkout.resolve():
        raise click.ClickException(f"run provision from the target Git checkout root: {root}")
    branch = runner.run_isolated(("git", "-C", str(root), "branch", "--show-current"), git_environment).stdout.strip()
    if not branch:
        raise click.ClickException("target Git checkout must be on a branch")
    remote_name = _git_config(runner, root, git_environment, f"branch.{branch}.pushRemote")
    remote_name = (
        remote_name
        or _git_config(runner, root, git_environment, "remote.pushDefault")
        or _git_config(runner, root, git_environment, f"branch.{branch}.remote")
    )
    remote_name = remote_name or "origin"
    if re.fullmatch(r"[A-Za-z0-9._-]+", remote_name) is None:
        raise click.ClickException("effective Git push remote name is unsafe")
    remote_urls = tuple(
        item
        for item in runner.run_isolated(
            ("git", "-C", str(root), "remote", "get-url", "--push", "--all", remote_name), git_environment
        ).stdout.splitlines()
        if item
    )
    if len(remote_urls) != 1:
        raise click.ClickException("effective Git push remote must contain exactly one push URL")
    remote_url = remote_urls[0]
    repository_name = _remote_repository(remote_url)
    login = GitHubUser.model_validate_json(
        runner.run_isolated(("gh", "api", "--hostname", "github.com", "user"), gh_environment).stdout
    ).login
    view = GitHubView.model_validate_json(
        runner.run_isolated(
            ("gh", "repo", "view", repository_name, "--json", "nameWithOwner,defaultBranchRef"), gh_environment
        ).stdout
    )
    token = existing_github_token(runner, gh_environment)
    if repository_name.casefold() != view.name_with_owner.casefold():
        raise click.ClickException("effective Git push remote does not match the repository selected by gh")
    author = _git_author(
        runner.run_isolated(("git", "-C", str(root), "var", "GIT_AUTHOR_IDENT"), git_environment).stdout
    )
    ssh = _discover_ssh(runner, root, git_environment, remote_url, home)
    paths = _paths(context)
    source_config = paths.config_home / "opencode" / "opencode.json"
    auth_source = paths.data_home / "opencode" / "auth.json"
    if not source_config.is_file():
        raise click.ClickException(f"required OpenCode config does not exist: {source_config}")
    if auth_source.is_symlink() or not _user_file(auth_source, 0o600):
        raise click.ClickException(f"OpenCode auth must be a user-owned regular mode-0600 file: {auth_source}")
    source = OpenCodeSourceConfig.model_validate_json(source_config.read_text())
    provider_name, separator, model_name = source.model.partition("/")
    provider = source.provider.get(provider_name)
    if not separator or provider is None or model_name not in provider.models:
        raise click.ClickException("selected OpenCode model/provider is not completely configured")
    opencode_name = shutil.which("opencode")
    if opencode_name is None:
        raise click.ClickException("opencode executable is not installed on PATH")
    opencode_executable = Path(opencode_name).resolve()
    version = runner.run_isolated((str(opencode_executable), "--version"), git_environment).stdout.strip()
    if version != "1.17.20":
        raise click.ClickException(f"opencode 1.17.20 is required; found {version or 'no version'}")
    policy, payload = load_policy()
    effective_payload = restricted_opencode_config(policy, source.model, provider_name, provider, paths.worktree_root)
    lifecycle.validate_host()
    ocint_executable = lifecycle.validate_executable(installed_ocint())
    lifecycle.validate_lingering()
    require_available_loopback_port(4097)
    require_available_loopback_port(8732)
    _validate_managed_destinations(paths, lifecycle)
    return ProvisionDiscovery(
        checkout=root,
        login=login,
        github_repository=view.name_with_owner,
        default_branch=view.default_branch_ref.name,
        github_token=token,
        remote_url=remote_url,
        author=author,
        ssh=ssh,
        opencode=OpenCodeDiscovery(
            executable=opencode_executable,
            version=version,
            source_config=source_config,
            auth_source=auth_source,
            model=source.model,
            provider_name=provider_name,
            provider=provider,
        ),
        policy=policy,
        policy_bytes=payload,
        effective_opencode_payload=effective_payload,
        paths=paths,
        ocint_executable=ocint_executable,
    )


def provision(discovery: ProvisionDiscovery, lifecycle: SystemdLifecycle, context: DaemonContext) -> None:
    paths = discovery.paths
    config = discovered_daemon_config(discovery, _existing_policy(context))
    for directory in (
        paths.config_home / "ocint",
        paths.data_home / "ocint",
        paths.state_home / "ocint",
        paths.isolated_config_home,
        paths.isolated_config_home / "opencode",
    ):
        ensure_private_directory(directory)
    ensure_auth_symlink(discovery.opencode.auth_source, paths.isolated_data_home)
    current_api_token = _existing_api_token(paths.environment)
    write_private_file(
        paths.environment,
        f"OCINT_DAEMON_API_TOKEN={current_api_token or secrets.token_urlsafe(48)}\n"
        f"OCINT_DAEMON_GITHUB_TOKEN={discovery.github_token}\n",
    )
    write_private_file(
        paths.effective_opencode_config,
        discovery.effective_opencode_payload,
    )
    write_private_file(paths.configuration, daemon_toml(config))
    lifecycle.install(discovery.ocint_executable, config.lifecycle)


def _paths(context: DaemonContext) -> ProvisionPaths:
    managed = context.config_home / "ocint"
    isolated_config_home = managed / "opencode-xdg"
    return ProvisionPaths(
        home=context.home,
        config_home=context.config_home,
        data_home=context.data_home,
        state_home=context.state_home,
        worktree_root=context.data_home / "ocint" / "worktrees",
        isolated_config_home=isolated_config_home,
        isolated_data_home=context.data_home / "ocint" / "opencode-data",
        environment=managed / "daemon.env",
        configuration=managed / "daemon.toml",
        effective_opencode_config=isolated_config_home / "opencode" / "opencode.json",
    )


def _git_config(runner: CommandRunner, root: Path, environment: Mapping[str, str], key: str) -> str:
    try:
        return runner.run_isolated(("git", "-C", str(root), "config", "--get", key), environment).stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def _remote_repository(remote_url: str) -> str:
    scp = re.fullmatch(r"[^@\s]+@github\.com:([^\s]+?)(?:\.git)?", remote_url) if "://" not in remote_url else None
    if scp is not None:
        repository = scp.group(1)
    else:
        parsed = urlparse(remote_url)
        if parsed.scheme != "ssh" or parsed.hostname != "github.com":
            raise click.ClickException("effective Git push remote must be an SSH GitHub remote")
        repository = parsed.path.removeprefix("/").removesuffix(".git")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise click.ClickException("effective GitHub repository must be owner/repository")
    return repository


def _git_author(value: str) -> GitIdentity:
    match = re.fullmatch(r"(.+) <([^<>]+)> [0-9]+ [+-][0-9]{4}\s*", value)
    if match is None:
        raise click.ClickException("effective Git author name/email could not be discovered")
    return GitIdentity(name=match.group(1), email=match.group(2))


def _discover_ssh(
    runner: CommandRunner,
    root: Path,
    environment: Mapping[str, str],
    remote_url: str,
    home: Path,
) -> SshDiscovery:
    configured = _git_config(runner, root, environment, "core.sshCommand")
    arguments = shlex.split(configured) if configured else ["ssh"]
    if not arguments or any(re.search(r"[;&|`$<>\n]", item) for item in arguments):
        raise click.ClickException("core.sshCommand is empty or unsafe")
    executable_name = shutil.which(arguments[0])
    if executable_name is None:
        raise click.ClickException(f"effective SSH executable is not installed: {arguments[0]}")
    executable = Path(executable_name).resolve()
    destination = _ssh_destination(remote_url)
    destination_arguments = ["-G"]
    if destination.port is not None:
        destination_arguments.extend(("-p", str(destination.port)))
    if destination.user is not None:
        destination_arguments.extend(("-l", destination.user))
    destination_arguments.append(destination.host)
    rendered = runner.run_isolated((str(executable), *arguments[1:], *destination_arguments), environment).stdout
    identities: list[Path] = []
    known_hosts: list[Path] = []
    for line in rendered.splitlines():
        key, separator, value = line.partition(" ")
        if not separator:
            continue
        if key.lower() == "identityfile":
            path = _ssh_path(value, home)
            if path is not None and not path.is_symlink() and _user_file(path, 0o600):
                identities.append(path.resolve())
        elif key.lower() == "userknownhostsfile":
            for item in shlex.split(value):
                path = _ssh_path(item, home)
                if path is not None and path.is_file() and os.access(path, os.R_OK):
                    known_hosts.append(path.resolve())
    identities = list(dict.fromkeys(identities))
    known_hosts = list(dict.fromkeys(known_hosts))
    if len(identities) != 1:
        raise click.ClickException(
            "effective SSH configuration must select exactly one existing user-owned mode-0600 identity"
        )
    if len(known_hosts) != 1:
        raise click.ClickException("effective SSH configuration must select exactly one readable known-hosts file")
    return SshDiscovery(executable=executable, identity_file=identities[0], known_hosts_file=known_hosts[0])


def _ssh_destination(remote_url: str) -> SshDestination:
    if remote_url.startswith("ssh://"):
        parsed = urlparse(remote_url)
        if parsed.hostname is None:
            raise click.ClickException("effective Git push remote does not contain an SSH host")
        return SshDestination(host=parsed.hostname, user=parsed.username, port=parsed.port)
    match = re.fullmatch(r"([^@\s]+)@([^\s/:]+):.+", remote_url)
    if match is None:
        raise click.ClickException("effective Git push remote does not contain an SSH destination")
    return SshDestination(host=match.group(2), user=match.group(1))


def _ssh_path(value: str, home: Path) -> Path | None:
    cleaned = value.strip().replace("%d", str(home))
    if cleaned.lower() == "none" or "%" in cleaned:
        return None
    return Path(cleaned).expanduser()


def _user_file(path: Path, mode: int) -> bool:
    return path.is_file() and path.stat().st_uid == os.getuid() and stat.S_IMODE(path.stat().st_mode) == mode


def discovery_environment(context: DaemonContext, github: bool) -> dict[str, str]:
    names = ("PATH", "LANG", "LC_ALL", "USER", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")
    environment = {name: context.environment[name] for name in names if name in context.environment}
    environment["HOME"] = str(context.home)
    if github:
        for name in ("GH_CONFIG_DIR", "GH_TOKEN", "GITHUB_TOKEN"):
            if name in context.environment:
                environment[name] = context.environment[name]
    return environment


def _validate_managed_destinations(paths: ProvisionPaths, lifecycle: SystemdLifecycle) -> None:
    for directory in (
        paths.config_home / "ocint",
        paths.data_home / "ocint",
        paths.state_home / "ocint",
        paths.isolated_config_home,
        paths.isolated_config_home / "opencode",
        paths.isolated_data_home,
        paths.isolated_data_home / "opencode",
    ):
        if directory.exists() and (
            directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != os.getuid()
        ):
            raise click.ClickException(f"managed directory is unsafe: {directory}")
    for path in (paths.environment, paths.configuration, paths.effective_opencode_config):
        if path.exists() and (path.is_symlink() or not _user_file(path, 0o600)):
            raise click.ClickException(f"managed configuration must be a user-owned regular mode-0600 file: {path}")
    auth_link = paths.isolated_data_home / "opencode" / "auth.json"
    if os.path.lexists(auth_link) and (
        not auth_link.is_symlink()
        or auth_link.lstat().st_uid != os.getuid()
        or auth_link.resolve() != (paths.data_home / "opencode" / "auth.json").resolve()
    ):
        raise click.ClickException(f"managed OpenCode auth link is unsafe: {auth_link}")
    lifecycle.validate_install_paths()


def _existing_api_token(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        if line.startswith("OCINT_DAEMON_API_TOKEN="):
            return line.partition("=")[2]
    return ""


def _existing_policy(context: DaemonContext) -> tuple[LifecycleConfig, LoggingConfig]:
    if not context.config_path.exists():
        return (LifecycleConfig(), LoggingConfig())
    try:
        config = context.config()
        return (config.lifecycle, config.logging)
    except (OSError, ValueError) as error:
        raise click.ClickException(f"existing daemon lifecycle/logging config is invalid: {error}") from error


def discovered_daemon_config(
    discovery: ProvisionDiscovery, policy: tuple[LifecycleConfig, LoggingConfig]
) -> DaemonConfig:
    lifecycle, logging = policy
    paths = discovery.paths
    return DaemonConfig(
        database_path=paths.state_home / "ocint" / "daemon.sqlite",
        mirror_root=paths.data_home / "ocint" / "mirrors",
        worktree_root=paths.worktree_root,
        repositories=(
            RepositoryConfig(
                name=discovery.github_repository.partition("/")[2],
                remote_url=discovery.remote_url,
                default_branch=discovery.default_branch,
                github_repository=discovery.github_repository,
                author_name=discovery.author.name,
                author_email=discovery.author.email,
                actors=frozenset((discovery.login,)),
            ),
        ),
        lifecycle=lifecycle,
        logging=logging,
        opencode=OpenCodeConfig(
            executable=discovery.opencode.executable,
            config_file=paths.effective_opencode_config,
            xdg_config_home=paths.isolated_config_home,
            xdg_data_home=paths.isolated_data_home,
        ),
        github=GitHubConfig(agent_actor=discovery.login),
        git=GitConfig(
            ssh_executable=discovery.ssh.executable,
            identity_file=discovery.ssh.identity_file,
            known_hosts_file=discovery.ssh.known_hosts_file,
        ),
    )


def daemon_toml(config: DaemonConfig) -> str:
    repository = config.repositories[0]
    quote = json.dumps
    return f"""database_path = {quote(str(config.database_path))}
mirror_root = {quote(str(config.mirror_root))}
worktree_root = {quote(str(config.worktree_root))}
idle_timeout_seconds = {config.idle_timeout_seconds}

[[repositories]]
name = {quote(repository.name)}
remote_url = {quote(repository.remote_url)}
default_branch = {quote(repository.default_branch)}
github_repository = {quote(repository.github_repository)}
author_name = {quote(repository.author_name)}
author_email = {quote(repository.author_email)}
actors = [{quote(next(iter(repository.actors)))}]
checks = []

[lifecycle]
startup_delay_seconds = {config.lifecycle.startup_delay_seconds}
inactive_interval_seconds = {config.lifecycle.inactive_interval_seconds}

[logging]
max_bytes = {config.logging.max_bytes}
backup_count = {config.logging.backup_count}

[opencode]
server_url = {quote(str(config.opencode.server_url))}
username = {quote(config.opencode.username)}
expected_version = {quote(config.opencode.expected_version)}
executable = {quote(str(config.opencode.executable))}
config_file = {quote(str(config.opencode.config_file))}
xdg_config_home = {quote(str(config.opencode.xdg_config_home))}
xdg_data_home = {quote(str(config.opencode.xdg_data_home))}
startup_timeout_seconds = {config.opencode.startup_timeout_seconds}

[github]
issue_label = {quote(config.github.issue_label)}
agent_actor = {quote(config.github.agent_actor)}

[git]
ssh_executable = {quote(str(config.git.ssh_executable))}
identity_file = {quote(str(config.git.identity_file))}
known_hosts_file = {quote(str(config.git.known_hosts_file))}
"""
