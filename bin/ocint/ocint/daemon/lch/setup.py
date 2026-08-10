import json
import os
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import click
from pydantic import BaseModel, ConfigDict, Field

# FIXME: lch importing feature config directly needs to be refactored.
from ocint.daemon.config import (
    DaemonConfig,
    DaemonContext,
    GitConfig,
    LifecycleConfig,
    LoggingConfig,
    OpenCodeConfig,
    RepositoryConfig,
)
from ocint.daemon.github import GitHubConfig
from ocint.daemon.lch.opencode import (
    CoordinatorStaticOpenCodePolicy,
    OpenCodeProvider,
    OpenCodeSelection,
    OpenCodeSourceConfig,
    PrivateFilePurpose,
    PrivateFileRequirement,
    StaticOpenCodePolicy,
    coordinator_restricted_opencode_config,
    ensure_auth_symlink,
    ensure_private_directory,
    load_coordinator_policy,
    load_policy,
    provision_coordinator_runtime,
    restricted_opencode_config,
    upsert_private_environment,
    validate_opencode_source_file,
    validate_private_file,
    write_private_file,
)
from ocint.daemon.lch.systemd import (
    CommandRunner,
    CoordinatorUnitEnablement,
    SystemdLifecycle,
    discover_ngrok,
    discover_ngrok_runtime,
    installed_ocint,
)
from ocint.daemon.models import GitHubLogin


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
    coordinator_workspace: Path
    coordinator_isolated_config_home: Path
    coordinator_isolated_data_home: Path
    coordinator_effective_opencode_config: Path


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
    coordinator_policy: CoordinatorStaticOpenCodePolicy
    coordinator_policy_bytes: bytes
    coordinator_effective_opencode_payload: str
    repository_description: str = Field(min_length=1)
    paths: ProvisionPaths
    ocint_executable: Path
    ngrok_url: str


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


def discover(
    runner: CommandRunner,
    lifecycle: SystemdLifecycle,
    checkout: Path,
    context: DaemonContext,
    repository_description: str = "Personal configuration for OpenCode, Neovim, tmux, and terminals.",
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
    validated_source = validate_opencode_source_file(source_config)
    validated_auth = validate_private_file(
        PrivateFileRequirement(path=auth_source, purpose=PrivateFilePurpose.OPENCODE_AUTH)
    )
    source = OpenCodeSourceConfig.model_validate_json(validated_source.content)
    provider_name, separator, model_name = source.model.partition("/")
    provider = source.provider.get(provider_name)
    if not separator or provider is None or model_name not in provider.models:
        raise click.ClickException("selected OpenCode model/provider is not completely configured")
    opencode_name = shutil.which("opencode")
    if opencode_name is None:
        raise click.ClickException("opencode executable is not installed on PATH")
    opencode_executable = Path(opencode_name).resolve()
    version = runner.run_isolated((str(opencode_executable), "--version"), git_environment).stdout.strip()
    if version != "1.18.15":
        raise click.ClickException(f"opencode 1.18.15 is required; found {version or 'no version'}")
    policy, payload = load_policy()
    coordinator_policy, coordinator_payload = load_coordinator_policy()
    effective_payload = restricted_opencode_config(
        policy,
        source.model,
        provider_name,
        provider,
        paths.worktree_root,
        source.agent.build.options.service_tier,
    )
    coordinator_effective_payload = coordinator_restricted_opencode_config(
        coordinator_policy,
        source.model,
        provider_name,
        provider,
    )
    lifecycle.validate_host()
    ocint_executable = lifecycle.validate_executable(installed_ocint())
    lifecycle.validate_lingering()
    ngrok_url = _existing_environment_value(paths.environment, "OCINT_NGROK_URL") or context.environment.get(
        "OCINT_NGROK_URL", ""
    )
    discover_ngrok_runtime(runner, ngrok_url)
    require_available_loopback_port(4097)
    require_available_loopback_port(4098)
    require_available_loopback_port(8732)
    require_available_loopback_port(8733)
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
            source_config=validated_source.source_path,
            auth_source=validated_auth.path,
            model=source.model,
            provider_name=provider_name,
            provider=provider,
        ),
        policy=policy,
        policy_bytes=payload,
        effective_opencode_payload=effective_payload,
        coordinator_policy=coordinator_policy,
        coordinator_policy_bytes=coordinator_payload,
        coordinator_effective_opencode_payload=coordinator_effective_payload,
        repository_description=repository_description,
        paths=paths,
        ocint_executable=ocint_executable,
        ngrok_url=ngrok_url,
    )


def setup(discovery: ProvisionDiscovery, lifecycle: SystemdLifecycle) -> CoordinatorUnitEnablement:
    paths = discovery.paths
    validate_opencode_source_file(discovery.opencode.source_config)
    if os.path.lexists(paths.configuration):
        raise click.ClickException(
            f"daemon configuration already exists and will not be overwritten: {paths.configuration}"
        )
    config = discovered_daemon_config(discovery, (LifecycleConfig(), LoggingConfig()))
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
    assignments = {
        "OCINT_DAEMON_API_TOKEN": current_api_token or secrets.token_urlsafe(48),
        "OCINT_DAEMON_GITHUB_TOKEN": discovery.github_token,
        "OCINT_NGROK_URL": discovery.ngrok_url,
    }
    for name in (
        "OCINT_DAEMON_SLACK_BOT_TOKEN",
        "OCINT_DAEMON_SLACK_SIGNING_SECRET",
    ):
        existing = _existing_environment_value(paths.environment, name)
        if existing:
            assignments[name] = existing
    upsert_private_environment(
        paths.environment,
        assignments,
    )
    write_private_file(
        paths.effective_opencode_config,
        discovery.effective_opencode_payload,
    )
    write_private_file(paths.configuration, daemon_toml(config))
    provision_coordinator_runtime(
        config,
        OpenCodeSelection(
            model=discovery.opencode.model,
            provider_name=discovery.opencode.provider_name,
            provider=discovery.opencode.provider,
        ),
        discovery.opencode.auth_source,
    )
    ngrok = discover_ngrok(lifecycle.runner, paths.environment)
    return lifecycle.install(discovery.ocint_executable, config.lifecycle, config.coordinator.ingress.port, ngrok)


def _paths(context: DaemonContext) -> ProvisionPaths:
    managed = context.config_home / "ocint"
    isolated_config_home = managed / "opencode-xdg"
    coordinator_isolated_config_home = managed / "coordinator-opencode-xdg"
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
        coordinator_workspace=context.data_home / "ocint" / "coordinator",
        coordinator_isolated_config_home=coordinator_isolated_config_home,
        coordinator_isolated_data_home=context.data_home / "ocint" / "coordinator-opencode-data",
        coordinator_effective_opencode_config=(coordinator_isolated_config_home / "opencode" / "opencode.json"),
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
        paths.coordinator_workspace,
        paths.coordinator_isolated_config_home,
        paths.coordinator_isolated_config_home / "opencode",
        paths.coordinator_isolated_data_home,
        paths.coordinator_isolated_data_home / "opencode",
    ):
        if directory.exists() and (
            directory.is_symlink() or not directory.is_dir() or directory.stat().st_uid != os.getuid()
        ):
            raise click.ClickException(f"managed directory is unsafe: {directory}")
    for path in (
        paths.environment,
        paths.configuration,
        paths.effective_opencode_config,
        paths.coordinator_effective_opencode_config,
    ):
        if path.exists() and (path.is_symlink() or not _user_file(path, 0o600)):
            raise click.ClickException(f"managed configuration must be a user-owned regular mode-0600 file: {path}")
    auth_link = paths.isolated_data_home / "opencode" / "auth.json"
    coordinator_auth_link = paths.coordinator_isolated_data_home / "opencode" / "auth.json"
    for link in (auth_link, coordinator_auth_link):
        if os.path.lexists(link) and (
            not link.is_symlink()
            or link.lstat().st_uid != os.getuid()
            or link.resolve() != (paths.data_home / "opencode" / "auth.json").resolve()
        ):
            raise click.ClickException(f"managed OpenCode auth link is unsafe: {link}")
    lifecycle.validate_install_paths()


def _existing_api_token(path: Path) -> str:
    return _existing_environment_value(path, "OCINT_DAEMON_API_TOKEN")


def _existing_environment_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.partition("=")[2]
    return ""


def discovered_daemon_config(
    discovery: ProvisionDiscovery, policy: tuple[LifecycleConfig, LoggingConfig]
) -> DaemonConfig:
    lifecycle, logging = policy
    paths = discovery.paths
    return DaemonConfig.model_validate(
        {
            "database_path": paths.state_home / "ocint" / "daemon.sqlite",
            "mirror_root": paths.data_home / "ocint" / "mirrors",
            "worktree_root": paths.worktree_root,
            "repositories": (
                RepositoryConfig(
                    name=discovery.github_repository.partition("/")[2],
                    description=discovery.repository_description,
                    remote_url=discovery.remote_url,
                    default_branch=discovery.default_branch,
                    github_repository=discovery.github_repository,
                    author_name=discovery.author.name,
                    author_email=discovery.author.email,
                    actors=frozenset((GitHubLogin(discovery.login),)),
                ),
            ),
            "lifecycle": lifecycle,
            "logging": logging,
            "opencode": OpenCodeConfig(
                executable=discovery.opencode.executable,
                config_file=paths.effective_opencode_config,
                xdg_config_home=paths.isolated_config_home,
                xdg_data_home=paths.isolated_data_home,
            ),
            "coordinator": {
                "workspace_root": paths.coordinator_workspace,
                "turn_timeout_seconds": 1800,
                "shutdown_timeout_seconds": 30,
                "orphan_retention_seconds": 86400,
                "retry_seconds": 5,
                "max_turn_retries": 3,
                "response_chunk_characters": 3500,
                "slack_post_interval_seconds": 1,
                "ingress": {
                    "host": "127.0.0.1",
                    "port": 8733,
                    "max_request_bytes": 65536,
                    "timestamp_tolerance_seconds": 300,
                },
                "slack": {
                    "workspace_id": "T021N0EQ3JQ",
                    "channels": (
                        {
                            "channel_id": "C0955FD2FK4",
                            "authorized_users": frozenset(("U067EG8278R",)),
                        },
                    ),
                },
                "opencode": {
                    "server_url": "http://127.0.0.1:4098",
                    "executable": discovery.opencode.executable,
                    "config_file": paths.coordinator_effective_opencode_config,
                    "xdg_config_home": paths.coordinator_isolated_config_home,
                    "xdg_data_home": paths.coordinator_isolated_data_home,
                },
            },
            "github": GitHubConfig(agent_actor=GitHubLogin(discovery.login)),
            "git": GitConfig(
                ssh_executable=discovery.ssh.executable,
                identity_file=discovery.ssh.identity_file,
                known_hosts_file=discovery.ssh.known_hosts_file,
            ),
        }
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
description = {quote(repository.description)}
remote_url = {quote(repository.remote_url)}
default_branch = {quote(repository.default_branch)}
github_repository = {quote(repository.github_repository)}
author_name = {quote(repository.author_name)}
author_email = {quote(repository.author_email)}
actors = [{quote(str(next(iter(repository.actors))))}]
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

[api]
host = {quote(config.api.host)}
port = {config.api.port}

[coordinator]
workspace_root = {quote(str(config.coordinator.workspace_root))}
turn_timeout_seconds = {config.coordinator.turn_timeout_seconds}
shutdown_timeout_seconds = {config.coordinator.shutdown_timeout_seconds}
orphan_retention_seconds = {config.coordinator.orphan_retention_seconds}
retry_seconds = {config.coordinator.retry_seconds}
max_turn_retries = {config.coordinator.max_turn_retries}
response_chunk_characters = {config.coordinator.response_chunk_characters}
slack_post_interval_seconds = {config.coordinator.slack_post_interval_seconds}

[coordinator.ingress]
host = {quote(config.coordinator.ingress.host)}
port = {config.coordinator.ingress.port}
max_request_bytes = {config.coordinator.ingress.max_request_bytes}
    timestamp_tolerance_seconds = {config.coordinator.ingress.timestamp_tolerance_seconds}
processing_timeout_seconds = {config.coordinator.ingress.processing_timeout_seconds}
database_busy_timeout_ms = {config.coordinator.ingress.database_busy_timeout_ms}

[coordinator.slack]
workspace_id = {quote(config.coordinator.slack.workspace_id)}

[[coordinator.slack.channels]]
channel_id = {quote(config.coordinator.slack.channels[0].channel_id)}
authorized_users = [{", ".join(quote(user) for user in sorted(config.coordinator.slack.channels[0].authorized_users))}]

[coordinator.opencode]
server_url = {quote(str(config.coordinator.opencode.server_url))}
username = {quote(config.coordinator.opencode.username)}
request_timeout_seconds = {config.coordinator.opencode.request_timeout_seconds}
expected_version = {quote(config.coordinator.opencode.expected_version)}
executable = {quote(str(config.coordinator.opencode.executable))}
config_file = {quote(str(config.coordinator.opencode.config_file))}
xdg_config_home = {quote(str(config.coordinator.opencode.xdg_config_home))}
xdg_data_home = {quote(str(config.coordinator.opencode.xdg_data_home))}
startup_timeout_seconds = {config.coordinator.opencode.startup_timeout_seconds}
shutdown_timeout_seconds = {config.coordinator.opencode.shutdown_timeout_seconds}

[github]
issue_label = {quote(config.github.issue_label)}
agent_actor = {quote(str(config.github.agent_actor))}

[git]
ssh_executable = {quote(str(config.git.ssh_executable))}
identity_file = {quote(str(config.git.identity_file))}
known_hosts_file = {quote(str(config.git.known_hosts_file))}
"""
