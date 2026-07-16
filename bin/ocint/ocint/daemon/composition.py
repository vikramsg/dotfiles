import asyncio
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from pydantic import SecretStr

from ocint.daemon.api import ControlApiResources, create_control_app
from ocint.daemon.channels import ControlChannel, GitHubChannel, SlackChannel, SlackSocketChannel
from ocint.daemon.config import DaemonSettings, load_daemon_config
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.git import GitHubPublisher, ManagedCommand, RepositoryManager
from ocint.daemon.models import Channel, WorkRequest
from ocint.daemon.outbox_repository import OutboxRepository
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import ActiveConfig, DaemonRunner
from ocint.daemon.runner_repository import RunnerRepository
from ocint.daemon.runtime import OpenCodeRuntime
from ocint.daemon.service import accept_work
from ocint.daemon.workspace_repository import WorkspaceRepository


class ControlledUvicornServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def run_daemon(settings: DaemonSettings, home: Path, channels: list[Channel]) -> None:
    settings = _load_credentials(settings)
    loaded = load_daemon_config(settings, home)
    if not settings.api_token.get_secret_value():
        raise ValueError("OCINT_DAEMON_API_TOKEN is required")
    migrate_daemon_db(loaded.config.database_path)
    engine = create_daemon_engine(loaded.config.database_path)
    repository = ControlRepository(engine)
    active = ActiveConfig(loaded, home)
    command = ManagedCommand(
        loaded.config.scheduler.command_timeout_seconds,
        loaded.config.scheduler.command_output_bytes,
        frozenset(
            [
                settings.api_token.get_secret_value(),
                settings.github_token.get_secret_value(),
                settings.slack_token.get_secret_value(),
                settings.opencode_password.get_secret_value(),
            ]
        ),
    )
    validation_environment = {"PATH": settings.execution_path, "LANG": settings.execution_lang, "CI": "1"}
    git_environment = {
        "PATH": settings.execution_path,
        "LANG": settings.execution_lang,
        "HOME": str(settings.publication_home),
        "GIT_TERMINAL_PROMPT": "0",
    }
    if settings.ssh_auth_sock:
        git_environment["SSH_AUTH_SOCK"] = settings.ssh_auth_sock
    if settings.git_config_global is not None:
        git_environment["GIT_CONFIG_GLOBAL"] = str(settings.git_config_global)
    if settings.git_push_credential is not None:
        git_environment["OCINT_GIT_PUSH_CREDENTIAL"] = str(settings.git_push_credential)
    manager = RepositoryManager(
        loaded.config.mirror_root,
        loaded.config.worktree_root,
        command,
        validation_environment,
        git_environment,
    )
    runtime = OpenCodeRuntime(
        str(loaded.config.opencode.server_url),
        loaded.config.opencode.username,
        settings.opencode_password.get_secret_value(),
        loaded.config.opencode.request_timeout_seconds,
        loaded.config.opencode.expected_version,
    )
    await runtime.start()
    await runtime.health()
    publisher = GitHubPublisher(str(loaded.config.providers.github_api_url), settings.github_token.get_secret_value())

    def durable_submit(request: WorkRequest) -> None:
        accept_work(request, active.loaded.config, repository)

    configured_channels = [*channels, ControlChannel()]
    slack_ingress: list[SlackChannel] = []
    for github in loaded.config.channels.github:
        if not settings.github_token.get_secret_value():
            raise ValueError("OCINT_DAEMON_GITHUB_TOKEN is required for configured GitHub channels")
        configured_channels.append(
            GitHubChannel(
                str(loaded.config.providers.github_api_url),
                settings.github_token.get_secret_value(),
                github.repository,
                github.github_repository,
                github.label,
                github.poll_seconds,
                durable_submit,
            )
        )
    slack = loaded.config.channels.slack
    if slack.enabled:
        if not settings.slack_token.get_secret_value():
            raise ValueError("OCINT_DAEMON_SLACK_TOKEN is required for a configured Slack channel")
        if slack.socket_mode:
            configured_channels.append(
                SlackSocketChannel(
                    str(loaded.config.providers.slack_api_url),
                    str(loaded.config.providers.slack_socket_url),
                    settings.slack_token.get_secret_value(),
                    slack.channel_repositories,
                    durable_submit,
                )
            )
        else:
            slack_channel = SlackChannel(
                str(loaded.config.providers.slack_api_url),
                settings.slack_token.get_secret_value(),
                settings.slack_signing_secret.get_secret_value(),
                slack.channel_repositories,
                durable_submit,
            )
            configured_channels.append(slack_channel)
            slack_ingress.append(slack_channel)
    runner = DaemonRunner(
        active,
        repository,
        manager,
        runtime,
        publisher,
        configured_channels,
        OutboxRepository(engine),
        RunnerRepository(engine, repository),
        WorkspaceRepository(engine),
    )
    app = create_control_app(
        ControlApiResources(
            repository=repository,
            config_provider=active.current,
            reload_config=active.reload,
            token=settings.api_token.get_secret_value(),
            slack_channels=slack_ingress,
            runtime=runtime,
        )
    )
    server = ControlledUvicornServer(
        uvicorn.Config(
            app,
            host=loaded.config.api.host,
            port=loaded.config.api.port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    api_task = asyncio.create_task(server.serve())
    while not server.started:
        if api_task.done():
            await api_task
        await asyncio.sleep(0.01)
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGHUP, active.reload)
    loop.add_signal_handler(signal.SIGTERM, runner.stopping.set)
    loop.add_signal_handler(signal.SIGINT, runner.stopping.set)
    try:
        await runner.run()
    finally:
        runner.stopping.set()
        server.should_exit = True
        await api_task
        await runtime.close()
        engine.dispose()


def _load_credentials(settings: DaemonSettings) -> DaemonSettings:
    directory = settings.credential_directory
    if directory is None:
        return settings
    secret_files = {
        "api_token": directory / "daemon-api-token",
        "opencode_password": directory / "opencode-password",
        "github_token": directory / "github-token",
        "slack_token": directory / "slack-token",
        "slack_signing_secret": directory / "slack-signing-secret",
    }
    secret_updates = {
        name: SecretStr(path.read_text().strip()) for name, path in secret_files.items() if path.is_file()
    }
    resolved = settings.model_copy(update=secret_updates)
    git_config = directory / "git-config"
    path_updates = {"git_config_global": git_config} if git_config.is_file() else {}
    git_credential = directory / "git-push-credential"
    if git_credential.is_file():
        path_updates["git_push_credential"] = git_credential
    return resolved.model_copy(update=path_updates)
