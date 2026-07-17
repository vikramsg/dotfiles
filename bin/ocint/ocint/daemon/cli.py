import asyncio
import getpass
import json
import secrets
import tomllib
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import click
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from ocint._models import CliContext
from ocint.daemon.api import create_api_router
from ocint.daemon.config import DaemonConfig, DaemonSettings
from ocint.daemon.db import create_daemon_engine, current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.git import GitManager
from ocint.daemon.github import GitHubClient, GitHubRepository, GitHubService
from ocint.daemon.lch import SubprocessRunner, diagnose, lch, lifecycle
from ocint.daemon.opencode import OpenCodeClient
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import serve_bounded, wait_for_idle
from ocint.daemon.service import JobExecutor, WorkRequest


class LoadedDaemonConfig(BaseModel):
    """Configuration after the CLI integration has resolved and read its file."""

    model_config = ConfigDict(frozen=True)

    config: DaemonConfig
    settings: DaemonSettings


def load_daemon_config(settings: DaemonSettings, home: Path) -> LoadedDaemonConfig:
    path = settings.config_path(home)
    with path.open("rb") as stream:
        config = DaemonConfig.model_validate(tomllib.load(stream))
    return LoadedDaemonConfig(config=config, settings=settings)


@click.group()
def daemon() -> None:
    """Run and control the durable OpenCode orchestration daemon."""


daemon.add_command(lch)


@daemon.command("config")
@click.option("path_only", "--path", is_flag=True)
@click.pass_obj
def config_command(context: CliContext, path_only: bool) -> None:
    settings = DaemonSettings()
    path = settings.config_path(Path.home())
    if path_only:
        context.output.write(str(path), nl=True)
        return
    loaded = load_daemon_config(settings, Path.home())
    context.output.write(
        json.dumps({"config_path": str(path), "effective": json.loads(loaded.config.model_dump_json())}, indent=2),
        nl=True,
    )


@daemon.command("migrate")
@click.pass_obj
def migrate_command(context: CliContext) -> None:
    loaded = load_daemon_config(DaemonSettings(), Path.home())
    migrate_daemon_db(loaded.config.database_path)
    context.output.write(current_daemon_head_revision(), nl=True)


@daemon.command("doctor")
@click.option("json_output", "--json", is_flag=True)
@click.pass_context
def doctor_command(click_context: click.Context, json_output: bool) -> None:
    context = click_context.ensure_object(CliContext)
    report = diagnose(Path.home(), SubprocessRunner(), lifecycle(Path.home()))
    context.output.write(report.json_text() if json_output else report.human_text(), nl=False)
    if not report.healthy:
        click_context.exit(1)


@daemon.command("run")
def run_command() -> None:
    app, loaded = create_daemon_app(DaemonSettings(), Path.home())
    asyncio.run(
        serve_bounded(
            app,
            loaded.config.api.host,
            loaded.config.api.port,
            app.state.shutdown_event,
        )
    )


@daemon.command("health")
@click.pass_obj
def health_command(context: CliContext) -> None:
    context.output.write(asyncio.run(_request("GET", "/health")), nl=True)


@daemon.command("submit")
@click.argument("repository")
@click.argument("prompt")
@click.option("actor", "--actor", default="")
@click.option("key", "--idempotency-key", default="")
@click.pass_obj
def submit_command(context: CliContext, repository: str, prompt: str, actor: str, key: str) -> None:
    request = WorkRequest(
        idempotency_key=key or uuid.uuid4().hex,
        actor=actor or getpass.getuser(),
        repository=repository,
        prompt=prompt,
    )
    context.output.write(asyncio.run(_request("POST", "/api/jobs", request.model_dump(mode="json"))), nl=True)


@daemon.command("list")
@click.pass_obj
def list_command(context: CliContext) -> None:
    context.output.write(asyncio.run(_request("GET", "/api/jobs")), nl=True)


@daemon.command("status")
@click.argument("job_id")
@click.pass_obj
def status_command(context: CliContext, job_id: str) -> None:
    context.output.write(asyncio.run(_request("GET", f"/api/jobs/{job_id}")), nl=True)


def create_daemon_app(settings: DaemonSettings, home: Path) -> tuple[FastAPI, LoadedDaemonConfig]:
    loaded = load_daemon_config(settings, home)
    api_token = settings.api_token.get_secret_value()
    github_token = settings.github_token.get_secret_value()
    if not api_token:
        raise ValueError("OCINT_DAEMON_API_TOKEN is required")
    if not github_token:
        raise ValueError("OCINT_DAEMON_GITHUB_TOKEN is required")
    migrate_daemon_db(loaded.config.database_path)
    engine = create_daemon_engine(loaded.config.database_path)
    repository = ControlRepository(engine)
    validation_environment = {"PATH": settings.execution_path, "LANG": settings.execution_lang, "CI": "1"}
    git_environment = {
        "PATH": settings.execution_path,
        "LANG": settings.execution_lang,
        "GIT_TERMINAL_PROMPT": "0",
    }
    git = GitManager(
        loaded.config.mirror_root,
        loaded.config.worktree_root,
        validation_environment,
        git_environment,
        loaded.config.git.ssh_executable,
        loaded.config.git.identity_file,
        loaded.config.git.known_hosts_file,
        loaded.config.scheduler.command_timeout_seconds,
        loaded.config.scheduler.command_output_bytes,
    )
    opencode = OpenCodeClient(
        str(loaded.config.opencode.server_url),
        loaded.config.opencode.username,
        secrets.token_urlsafe(32),
        loaded.config.opencode.request_timeout_seconds,
        loaded.config.scheduler.job_timeout_seconds,
        loaded.config.opencode.expected_version,
        loaded.config.opencode.executable,
        loaded.config.opencode.config_file,
        loaded.config.opencode.xdg_config_home,
        loaded.config.opencode.xdg_data_home,
        loaded.config.opencode.startup_timeout_seconds,
        loaded.config.opencode.shutdown_timeout_seconds,
        settings.execution_path,
        settings.execution_lang,
    )
    github_client = GitHubClient(str(loaded.config.github.api_url), github_token)
    github = GitHubService(loaded.config, github_client, GitHubRepository(engine))
    executor = JobExecutor(loaded.config, repository, opencode, git, github)
    shutdown_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await opencode.start()
        try:
            await github_client.start()
            try:
                try:
                    await github.poll(executor)
                    await executor.start()
                    idle_task = asyncio.create_task(
                        wait_for_idle(executor, loaded.config.idle_timeout_seconds, shutdown_event)
                    )
                    try:
                        yield
                    finally:
                        idle_task.cancel()
                        await asyncio.gather(idle_task, return_exceptions=True)
                finally:
                    await executor.close()
            finally:
                await github_client.close()
        finally:
            await opencode.close()
            engine.dispose()

    app = FastAPI(title="ocint daemon", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(create_api_router(repository, executor.submit, api_token))
    app.state.shutdown_event = shutdown_event
    return app, loaded


async def _request(method: str, path: str, payload: Mapping[str, str] | None = None) -> str:
    loaded = load_daemon_config(DaemonSettings(), Path.home())
    token = loaded.settings.api_token.get_secret_value()
    if not token:
        raise click.ClickException("OCINT_DAEMON_API_TOKEN is required")
    host = "127.0.0.1" if loaded.config.api.host in {"0.0.0.0", "::"} else loaded.config.api.host
    async with (
        aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as client,
        client.request(method, f"http://{host}:{loaded.config.api.port}{path}", json=payload) as response,
    ):
        body = await response.text()
        if response.status >= 400:
            raise click.ClickException(f"daemon HTTP {response.status}: {body}")
        return body
