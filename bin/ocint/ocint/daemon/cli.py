import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import click
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from ocint._models import CliContext
from ocint.daemon import logging as daemon_logging
from ocint.daemon.api import create_api_router
from ocint.daemon.config import DaemonConfig, DaemonContext, LoggingConfig
from ocint.daemon.coordinator import (
    ChannelAccess,
    CoordinatorWorkspaceConfig,
    RepositoryCatalogueEntry,
    create_configured_authorization_policy,
    create_coordinator_operations,
    create_coordinator_worker,
    create_opencode_coordinator,
    generate_coordinator_workspace,
    open_coordinator_persistence,
    run_coordinator_application,
)
from ocint.daemon.db import current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.git import GitRuntimeConfig, create_git_manager
from ocint.daemon.github import (
    GitHubGateway,
    GitHubRepositoryPolicies,
    GitHubRepositoryPolicy,
    open_github_service,
)
from ocint.daemon.lch import SubprocessRunner, diagnose, lch, lifecycle, validate_coordinator_runtime
from ocint.daemon.models import GitRepository
from ocint.daemon.opencode import OpenCodeRuntimeConfig, create_opencode_client
from ocint.daemon.pull_request_job import (
    PullRequestJobConfig,
    RepositoryPolicy,
    SchedulerPolicy,
    create_pull_request_job_runner,
    open_pull_request_job_store,
)
from ocint.daemon.run import serve_bounded, serve_signal_free_ingress, wait_for_idle
from ocint.daemon.slack import (
    create_slack_events_app,
    open_slack_coordinator_delivery,
    production_slack_actor_policy,
    validate_coordinator_slack_access,
)
from ocint.daemon.tasks import SourceRouter, open_task_coordinator

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


@daemon.group("coordinator")
def coordinator_command() -> None:
    """Run the durable Slack coordinator."""


@coordinator_command.command("run")
@click.pass_obj
def coordinator_run_command(context: DaemonContext) -> None:
    daemon_logging.configure(daemon_logging.daemon_log_settings(context.state_home, LoggingConfig()))
    logger.info("coordinator started", pid=os.getpid())
    try:
        config = context.config()
        daemon_logging.configure(daemon_logging.daemon_log_settings(context.state_home, config.logging))
        asyncio.run(_run_coordinator(context))
        logger.info("coordinator stopped")
    except BaseException:
        logger.exception("coordinator failed")
        raise
    finally:
        daemon_logging.close()


@contextmanager
def open_daemon_app(
    context: DaemonContext, github: GitHubGateway, source: SourceRouter | None = None
) -> Iterator[DaemonApplication]:
    config = context.config()
    api_token = context.settings.api_token.get_secret_value()
    if not api_token:
        raise ValueError("OCINT_DAEMON_API_TOKEN is required")
    migrate_daemon_db(config.database_path)
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
    git = create_git_manager(
        GitRuntimeConfig(
            mirror_root=config.mirror_root,
            worktree_root=config.worktree_root,
            validation_environment=validation_environment,
            git_environment=git_environment,
            transport=config.git,
            timeout_seconds=config.scheduler.command_timeout_seconds,
            output_bytes=config.scheduler.command_output_bytes,
        )
    )
    opencode = create_opencode_client(
        OpenCodeRuntimeConfig(
            service=config.opencode,
            password=secrets.token_urlsafe(32),
            execution_timeout_seconds=config.scheduler.job_timeout_seconds,
            process_path=context.settings.execution_path,
            process_lang=context.settings.execution_lang,
        )
    )
    job_config = PullRequestJobConfig(
        repositories=tuple(
            RepositoryPolicy(
                git_repository=GitRepository(
                    name=item.name,
                    remote_url=item.remote_url,
                    default_branch=item.default_branch,
                ),
                github_repository=item.github_repository,
                author_name=item.author_name,
                author_email=item.author_email,
                actors=item.actors,
                checks=item.checks,
            )
            for item in config.repositories
        ),
        scheduler=SchedulerPolicy(
            capacity=config.scheduler.capacity,
            job_timeout_seconds=config.scheduler.job_timeout_seconds,
            shutdown_timeout_seconds=config.scheduler.shutdown_timeout_seconds,
        ),
    )
    with open_pull_request_job_store(config.database_path) as repository:
        executor = create_pull_request_job_runner(job_config, repository, opencode, git, github)
        with open_task_coordinator(config.database_path, source or SourceRouter((github,)), executor) as coordinator:
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

            app = FastAPI(title="ocint daemon", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
            app.include_router(create_api_router(repository, executor.submit, api_token, opencode))
            yield DaemonApplication(app=app, config=config, shutdown_event=shutdown_event)


async def _run_daemon(context: DaemonContext) -> None:
    config = context.config()
    token = context.settings.github_token.get_secret_value()
    if not token:
        raise ValueError("OCINT_DAEMON_GITHUB_TOKEN is required")
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
        with open_daemon_app(context, github, SourceRouter((github,))) as application:
            await serve_bounded(
                application.app, application.config.api.host, application.config.api.port, application.shutdown_event
            )


async def _run_coordinator(context: DaemonContext) -> None:
    config = context.config()
    coordinator = config.coordinator
    bot_token = context.settings.slack_bot_token.get_secret_value()
    signing_secret = context.settings.slack_signing_secret.get_secret_value()
    if not bot_token:
        raise ValueError("OCINT_DAEMON_SLACK_BOT_TOKEN is required")
    if not signing_secret:
        raise ValueError("OCINT_DAEMON_SLACK_SIGNING_SECRET is required")

    validate_coordinator_runtime(context, config)
    await validate_coordinator_slack_access(coordinator.slack, bot_token)
    migrate_daemon_db(config.database_path)
    generate_coordinator_workspace(
        CoordinatorWorkspaceConfig(
            root=coordinator.workspace_root,
            repositories=tuple(
                RepositoryCatalogueEntry(
                    name=repository.name,
                    description=repository.description,
                    github_repository=repository.github_repository,
                    default_branch=repository.default_branch,
                )
                for repository in config.repositories
            ),
        )
    )

    authorization = create_configured_authorization_policy(
        tuple(
            ChannelAccess(
                provider="slack",
                workspace=coordinator.slack.workspace_id,
                channel=channel.channel_id,
                authorized_actors=channel.authorized_users,
            )
            for channel in coordinator.slack.channels
        )
    )
    service = create_coordinator_operations(
        authorization,
        coordinator.response_chunk_characters,
        coordinator.safe_failure_text,
    )
    with open_coordinator_persistence(config.database_path, coordinator.ingress.database_busy_timeout_ms) as repository:
        opencode = create_opencode_client(
            OpenCodeRuntimeConfig(
                service=coordinator.opencode,
                password=secrets.token_urlsafe(32),
                execution_timeout_seconds=coordinator.turn_timeout_seconds,
                process_path=context.settings.execution_path,
                process_lang=context.settings.execution_lang,
            )
        )
        async with open_slack_coordinator_delivery(bot_token) as delivery:
            runtime = create_coordinator_worker(
                repository,
                service,
                create_opencode_coordinator(opencode, coordinator.workspace_root),
                delivery,
                coordinator.workspace_root,
                coordinator.retry_seconds,
                coordinator.max_turn_retries,
                coordinator.orphan_retention_seconds,
                coordinator.slack_post_interval_seconds,
            )
            app = create_slack_events_app(
                coordinator.ingress,
                coordinator.slack.workspace_id,
                signing_secret,
                service.prepare,
                repository.ingest,
                production_slack_actor_policy(),
                runtime.wake,
            )

            async def serve_ingress(shutdown: asyncio.Event) -> None:
                await serve_signal_free_ingress(app, coordinator.ingress.host, coordinator.ingress.port, shutdown)

            await run_coordinator_application(
                runtime,
                opencode,
                serve_ingress,
                coordinator.ingress.host,
                coordinator.ingress.port,
                context.state_home / "ocint" / "coordinator.lock",
                coordinator.shutdown_timeout_seconds,
            )
