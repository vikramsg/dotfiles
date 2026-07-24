import asyncio
import json
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import click
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from ocint._models import CliContext
from ocint.daemon import logging as daemon_logging
from ocint.daemon.api import create_api_router
from ocint.daemon.config import DaemonConfig, DaemonContext, LoggingConfig
from ocint.daemon.db import create_daemon_engine, current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.git import GitManager
from ocint.daemon.github import (
    GitHubGateway,
    GitHubRepositoryPolicies,
    GitHubRepositoryPolicy,
    open_github_service,
)
from ocint.daemon.lch import SubprocessRunner, diagnose, lch, lifecycle
from ocint.daemon.models import DirectOrigin, GitHubLogin, WorkRequest
from ocint.daemon.opencode import OpenCodeClient
from ocint.daemon.repository import ControlRepository
from ocint.daemon.run import serve_bounded, wait_for_idle
from ocint.daemon.service import JobExecutor
from ocint.daemon.tasks import TaskCoordinator
from ocint.daemon.tasks.repository import TaskRepository

logger = daemon_logging.get_logger("cli")


class DaemonApplication(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    app: FastAPI
    config: DaemonConfig
    shutdown_event: asyncio.Event


@click.group()
@click.pass_context
def daemon(click_context: click.Context) -> None:
    """Run and control the durable OpenCode orchestration daemon."""
    root = click_context.ensure_object(CliContext)
    if not isinstance(click_context.obj, DaemonContext):
        click_context.obj = DaemonContext.create(root.output, Path.home(), os.environ)


daemon.add_command(lch)


@daemon.command("config")
@click.option("path_only", "--path", is_flag=True)
@click.pass_obj
def config_command(context: DaemonContext, path_only: bool) -> None:
    path = context.config_path
    if path_only:
        context.output.write(str(path), nl=True)
        return
    context.output.write(
        json.dumps({"config_path": str(path), "effective": json.loads(context.config().model_dump_json())}, indent=2),
        nl=True,
    )


@daemon.command("migrate")
@click.pass_obj
def migrate_command(context: DaemonContext) -> None:
    migrate_daemon_db(context.config().database_path)
    context.output.write(current_daemon_head_revision(), nl=True)


@daemon.command("doctor")
@click.option("json_output", "--json", is_flag=True)
@click.pass_context
def doctor_command(click_context: click.Context, json_output: bool) -> None:
    context = click_context.ensure_object(DaemonContext)
    report = diagnose(context, SubprocessRunner(), lifecycle(context))
    context.output.write(report.json_text() if json_output else report.human_text(), nl=False)
    if not report.healthy:
        click_context.exit(1)


@daemon.command("run")
@click.pass_obj
def run_command(context: DaemonContext) -> None:
    daemon_logging.configure(daemon_logging.daemon_log_settings(context.state_home, LoggingConfig()))
    logger.info("daemon cycle started", pid=os.getpid())
    try:
        config = context.config()
        daemon_logging.configure(daemon_logging.daemon_log_settings(context.state_home, config.logging))
        asyncio.run(_run_daemon(context))
        logger.info("daemon cycle completed")
    except BaseException:
        logger.exception("daemon cycle failed")
        raise
    finally:
        daemon_logging.close()


@daemon.command("health")
@click.pass_obj
def health_command(context: DaemonContext) -> None:
    context.output.write(asyncio.run(_request(context, "GET", "/health")), nl=True)


@daemon.command("submit")
@click.argument("repository")
@click.argument("prompt")
@click.option("actor", "--actor", required=True)
@click.option("key", "--idempotency-key", default="")
@click.pass_obj
def submit_command(context: DaemonContext, repository: str, prompt: str, actor: str, key: str) -> None:
    request = WorkRequest(
        idempotency_key=key or uuid.uuid4().hex,
        actor=GitHubLogin(actor),
        repository=repository,
        prompt=prompt,
        origin=DirectOrigin(),
    )
    context.output.write(asyncio.run(_request(context, "POST", "/api/jobs", request.model_dump(mode="json"))), nl=True)


@daemon.command("list")
@click.pass_obj
def list_command(context: DaemonContext) -> None:
    context.output.write(asyncio.run(_request(context, "GET", "/api/jobs")), nl=True)


@daemon.command("status")
@click.argument("job_id")
@click.pass_obj
def status_command(context: DaemonContext, job_id: str) -> None:
    context.output.write(asyncio.run(_request(context, "GET", f"/api/jobs/{job_id}")), nl=True)


def create_daemon_app(context: DaemonContext, github: GitHubGateway) -> DaemonApplication:
    config = context.config()
    api_token = context.settings.api_token.get_secret_value()
    if not api_token:
        raise ValueError("OCINT_DAEMON_API_TOKEN is required")
    migrate_daemon_db(config.database_path)
    engine = create_daemon_engine(config.database_path)
    repository = ControlRepository(engine)
    validation_environment = {
        "PATH": context.settings.execution_path,
        "LANG": context.settings.execution_lang,
        "CI": "1",
    }
    git_environment = {
        "PATH": context.settings.execution_path,
        "LANG": context.settings.execution_lang,
        "GIT_TERMINAL_PROMPT": "0",
    }
    git = GitManager(
        config.mirror_root,
        config.worktree_root,
        validation_environment,
        git_environment,
        config.git.ssh_executable,
        config.git.identity_file,
        config.git.known_hosts_file,
        config.scheduler.command_timeout_seconds,
        config.scheduler.command_output_bytes,
    )
    opencode = OpenCodeClient(
        str(config.opencode.server_url),
        config.opencode.username,
        secrets.token_urlsafe(32),
        config.opencode.request_timeout_seconds,
        config.scheduler.job_timeout_seconds,
        config.opencode.expected_version,
        config.opencode.executable,
        config.opencode.config_file,
        config.opencode.xdg_config_home,
        config.opencode.xdg_data_home,
        config.opencode.startup_timeout_seconds,
        config.opencode.shutdown_timeout_seconds,
        context.settings.execution_path,
        context.settings.execution_lang,
    )
    tasks = TaskRepository(engine)
    executor = JobExecutor(config, repository, opencode, git, github)
    coordinator = TaskCoordinator(github, tasks, executor)
    shutdown_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info("OpenCode startup started", executable=str(config.opencode.executable))
        await opencode.start()
        logger.info("OpenCode startup completed", version=config.opencode.expected_version)
        try:
            pending = executor.recover()
            logger.info("task reconciliation started")
            await coordinator.reconcile()
            logger.info("task reconciliation completed")
            executor.schedule_pending(pending)
            logger.info("daemon ready", api_port=config.api.port)
            idle_task = asyncio.create_task(
                wait_for_idle(executor, config.idle_timeout_seconds, shutdown_event, coordinator)
            )
            try:
                yield
            finally:
                idle_task.cancel()
                await asyncio.gather(idle_task, return_exceptions=True)
                await executor.close()
        finally:
            logger.info("OpenCode shutdown started")
            await opencode.close()
            logger.info("OpenCode shutdown completed")
            engine.dispose()

    app = FastAPI(title="ocint daemon", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(create_api_router(repository, executor.submit, api_token))
    return DaemonApplication(app=app, config=config, shutdown_event=shutdown_event)


async def _run_daemon(context: DaemonContext) -> None:
    config = context.config()
    token = context.settings.github_token.get_secret_value()
    if not token:
        raise ValueError("OCINT_DAEMON_GITHUB_TOKEN is required")
    migrate_daemon_db(config.database_path)
    repositories = GitHubRepositoryPolicies(
        root=[
            GitHubRepositoryPolicy(
                name=repository.name,
                github_repository=repository.github_repository,
                actors=repository.actors,
            )
            for repository in config.repositories
        ]
    )
    async with open_github_service(config.github, repositories, token, config.database_path) as github:
        application = create_daemon_app(context, github)
        await serve_bounded(
            application.app,
            application.config.api.host,
            application.config.api.port,
            application.shutdown_event,
        )


async def _request(context: DaemonContext, method: str, path: str, payload: Mapping[str, str] | None = None) -> str:
    config = context.config()
    token = context.settings.api_token.get_secret_value()
    if not token:
        raise click.ClickException("OCINT_DAEMON_API_TOKEN is required")
    host = "127.0.0.1" if config.api.host in {"0.0.0.0", "::"} else config.api.host
    async with (
        aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as client,
        client.request(method, f"http://{host}:{config.api.port}{path}", json=payload) as response,
    ):
        body = await response.text()
        if response.status >= 400:
            raise click.ClickException(f"daemon HTTP {response.status}: {body}")
        return body
