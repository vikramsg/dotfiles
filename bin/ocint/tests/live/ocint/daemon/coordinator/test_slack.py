import asyncio
import os
import socket
import subprocess
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import aiohttp
import pytest
from ocint.daemon.config import DaemonContext, DaemonSettings
from ocint.daemon.coordinator.config import (
    CoordinatorWorkspaceConfig,
    RepositoryCatalogueEntry,
)
from ocint.daemon.coordinator.models import ActorKind
from ocint.daemon.coordinator.opencode import OpenCodeCoordinatorAdapter
from ocint.daemon.coordinator.repository import CoordinatorRepository
from ocint.daemon.coordinator.run import (
    CoordinatorApplicationRequest,
    CoordinatorRuntime,
    open_coordinator_application,
)
from ocint.daemon.coordinator.service import ChannelAccess, ConfiguredAuthorizationPolicy, CoordinatorService
from ocint.daemon.coordinator.workspace import CoordinatorWorkspace
from ocint.daemon.db import create_daemon_engine, migrate_daemon_db
from ocint.daemon.db.schema import (
    coordinator_conversation,
    coordinator_delivery,
    coordinator_event,
    coordinator_turn,
    job,
    task,
    task_message,
    thread_message,
)
from ocint.daemon.lch import (
    AioHttpStaticEndpointTransport,
    StaticEndpointClassifier,
    StaticEndpointPreflightClient,
    StaticEndpointPreflightConfig,
    SubprocessRunner,
    coordinator_ngrok_command,
    discover_ngrok_runtime,
    require_static_endpoint_offline,
    scrubbed_subprocess_environment,
    validate_coordinator_runtime,
)
from ocint.daemon.logging import DaemonLogSettings, close, configure, get_logger
from ocint.daemon.opencode import OpenCodeRuntimeConfig, create_opencode_client
from ocint.daemon.run import serve_signal_free_ingress
from ocint.daemon.slack import create_slack_events_app, open_slack_coordinator_delivery
from ocint.daemon.slack.client import SlackClient
from ocint.daemon.slack.models import SlackEventCallback
from ocint.presentation import default_cli_context
from sqlalchemy import and_, or_, select


@dataclass(frozen=True)
class ExactXoxpProbeClassifier:
    workspace: str
    channel: str
    authorized_user: str
    client_message_id: str
    exact_prompt: str

    def classify(self, callback: SlackEventCallback) -> ActorKind:
        event = callback.event
        try:
            UUID(event.client_msg_id)
        except ValueError:
            return ActorKind.BOT
        exact_probe = (
            callback.team_id == self.workspace
            and event.type == "message"
            and event.channel_type == "channel"
            and event.channel == self.channel
            and event.user == self.authorized_user
            and event.client_msg_id == self.client_message_id
            and event.text == self.exact_prompt
            and bool(event.bot_id)
            and bool(event.app_id)
            and not event.thread_ts
        )
        return ActorKind.HUMAN if exact_probe else ActorKind.BOT


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_slack_ngrok_and_opencode_coordinator_path_preserves_probe_evidence() -> None:
    # GIVEN
    actor_user_token = os.environ.get("OCINT_E2E_SLACK_ACTOR_USER_TOKEN", "")
    process_environment = scrubbed_subprocess_environment(os.environ)
    settings = DaemonSettings()
    context = DaemonContext.create(default_cli_context().output, Path.home(), process_environment, settings)
    if not context.config_path.is_file():
        pytest.fail("live coordinator test requires the current daemon configuration")
    config = context.config()
    coordinator = config.coordinator
    production_bot_token = settings.slack_bot_token.get_secret_value()
    signing_secret = settings.slack_signing_secret.get_secret_value()
    ngrok_url = settings.ngrok_url.get_secret_value()
    if not production_bot_token or not signing_secret or not ngrok_url:
        pytest.fail("live coordinator test requires exported Slack and ngrok credentials")
    if not actor_user_token.startswith("xoxp-"):
        pytest.fail("live coordinator test requires the E2E actor User OAuth token")
    if not config.database_path.is_file():
        pytest.fail("live coordinator test requires the existing shared daemon database")
    if coordinator.ingress.port != 8_733 or coordinator.opencode.server_url.port != 4_098:
        pytest.fail("live coordinator test requires configured ports 8733 and 4098")
    channel = next((item for item in coordinator.slack.channels if item.channel_id == "C0955FD2FK4"), None)
    if channel is None:
        pytest.fail("live coordinator test requires configured channel C0955FD2FK4")

    for unit in ("ocint-coordinator.service", "ocint-coordinator-ngrok.service"):
        try:
            state = subprocess.run(
                ("systemctl", "--user", "is-active", unit),
                check=False,
                capture_output=True,
                text=True,
                env={
                    name: process_environment[name]
                    for name in ("DBUS_SESSION_BUS_ADDRESS", "HOME", "LANG", "PATH", "XDG_RUNTIME_DIR")
                    if name in process_environment
                },
            )
        except OSError:
            pytest.fail("live coordinator test could not inspect production systemd units")
        if state.returncode == 0:
            pytest.fail("live coordinator test requires production coordinator and ngrok units to be inactive")
    for port in (8_733, 4_098):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
            probe_socket.settimeout(0.2)
            if probe_socket.connect_ex(("127.0.0.1", port)) == 0:
                pytest.fail(f"live coordinator test requires loopback port {port} to be free")

    try:
        ngrok = discover_ngrok_runtime(SubprocessRunner(), ngrok_url)
    except RuntimeError:
        pytest.fail("live coordinator test requires a valid ngrok v3 static URL runtime")
    validate_coordinator_runtime(context, config)
    preflight_config = StaticEndpointPreflightConfig()
    await require_static_endpoint_offline(
        f"{ngrok_url.rstrip('/')}/slack/events",
        StaticEndpointPreflightClient(
            AioHttpStaticEndpointTransport(),
            StaticEndpointClassifier(preflight_config),
            preflight_config,
        ),
    )
    migrate_daemon_db(config.database_path)
    CoordinatorWorkspace(
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
    ).generate()

    probe = str(uuid4())
    prompt = f"Echo this exact probe UUID: {probe}. Then identify dotfiles from the repository catalogue."
    engine = create_daemon_engine(
        config.database_path,
        busy_timeout_ms=coordinator.ingress.database_busy_timeout_ms,
    )
    with engine.connect() as connection:
        tasks_before = frozenset(
            connection.execute(
                select(task.c.id)
                .select_from(
                    task.join(task_message, task_message.c.task_id == task.c.id).join(
                        thread_message, thread_message.c.id == task_message.c.message_id
                    )
                )
                .where(thread_message.c.body.contains(probe))
            ).scalars()
        )
        jobs_before = frozenset(
            connection.execute(
                select(job.c.id).where(or_(job.c.prompt.contains(probe), job.c.title.contains(probe)))
            ).scalars()
        )
    worktrees_before = (
        frozenset(path.relative_to(config.worktree_root) for path in config.worktree_root.rglob("*"))
        if config.worktree_root.is_dir()
        else frozenset()
    )

    production_slack_client = SlackClient(production_bot_token)
    actor_slack_client = SlackClient(actor_user_token)
    opencode = create_opencode_client(
        OpenCodeRuntimeConfig(
            service=coordinator.opencode,
            password=os.urandom(32).hex(),
            execution_timeout_seconds=coordinator.turn_timeout_seconds,
            process_path=settings.execution_path,
            process_lang=settings.execution_lang,
        )
    )
    ngrok_process: asyncio.subprocess.Process | None = None
    log_directory = context.state_home / "ocint"
    log_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_directory.chmod(0o700)
    live_log = log_directory / "live-e2e.log"
    ngrok_log = log_directory / "live-e2e-ngrok.log"
    if ngrok_log.is_symlink() or (ngrok_log.exists() and not ngrok_log.is_file()):
        pytest.fail("live coordinator ngrok log must be a regular non-symlink file")
    ngrok_log_descriptor = os.open(ngrok_log, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.fchmod(ngrok_log_descriptor, 0o600)
    ngrok_log_stream = os.fdopen(ngrok_log_descriptor, "ab", buffering=0)
    configure(DaemonLogSettings(path=live_log, max_bytes=10 * 1024 * 1024, backups=1))
    live_logger = get_logger("coordinator.live")
    live_logger.info("Live coordinator probe started", probe=probe)
    ngrok_log_stream.write(f"probe={probe} event=ngrok_harness_start\n".encode())

    try:
        await production_slack_client.start()
        await actor_slack_client.start()
        production_auth = await production_slack_client.auth_test()
        if production_auth.team_id != coordinator.slack.workspace_id or not production_auth.bot_id:
            pytest.fail("live coordinator Slack token does not match the configured workspace bot")
        missing_scopes = coordinator.slack.required_scopes - production_slack_client.granted_scopes
        if missing_scopes:
            pytest.fail("live coordinator Slack token is missing required scopes")
        actor_auth = await actor_slack_client.auth_test()
        if (
            actor_auth.team_id != coordinator.slack.workspace_id
            or not actor_auth.user_id
            or actor_auth.bot_id
            or actor_auth.user_id not in channel.authorized_users
        ):
            pytest.fail("live coordinator E2E actor must be an authorized user in the configured workspace")
        if "chat:write" not in actor_slack_client.granted_scopes:
            pytest.fail("live coordinator E2E actor User OAuth token is missing chat:write")

        repository = CoordinatorRepository(engine)
        service = CoordinatorService(
            ConfiguredAuthorizationPolicy(
                tuple(
                    ChannelAccess(
                        provider="slack",
                        workspace=coordinator.slack.workspace_id,
                        channel=configured_channel.channel_id,
                        authorized_actors=configured_channel.authorized_users,
                    )
                    for configured_channel in coordinator.slack.channels
                )
            ),
            coordinator.response_chunk_characters,
            coordinator.safe_failure_text,
        )

        async with (
            open_slack_coordinator_delivery(production_bot_token) as delivery,
            AsyncExitStack() as lifecycle_stack,
        ):
            try:
                runtime = CoordinatorRuntime(
                    repository,
                    service,
                    OpenCodeCoordinatorAdapter(opencode, coordinator.workspace_root),
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
                    ExactXoxpProbeClassifier(
                        workspace=coordinator.slack.workspace_id,
                        channel=channel.channel_id,
                        authorized_user=actor_auth.user_id,
                        client_message_id=probe,
                        exact_prompt=prompt,
                    ),
                    runtime.wake,
                )

                async def serve_ingress(shutdown: asyncio.Event) -> None:
                    await serve_signal_free_ingress(app, coordinator.ingress.host, coordinator.ingress.port, shutdown)

                application = await lifecycle_stack.enter_async_context(
                    open_coordinator_application(
                        CoordinatorApplicationRequest(
                            runtime=runtime,
                            opencode=opencode,
                            ingress=serve_ingress,
                            ingress_host=coordinator.ingress.host,
                            ingress_port=coordinator.ingress.port,
                            runtime_lock=context.state_home / "ocint" / "coordinator.lock",
                            shutdown_timeout_seconds=coordinator.shutdown_timeout_seconds,
                        )
                    )
                )

                # WHEN
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1)) as readiness_client:
                    async with asyncio.timeout(15):
                        while True:
                            try:
                                async with readiness_client.get(
                                    f"http://127.0.0.1:{coordinator.ingress.port}/slack/events"
                                ) as response:
                                    if response.status == 405:
                                        break
                            except aiohttp.ClientError, TimeoutError:
                                pass
                            await asyncio.sleep(0.1)

                ngrok_process = await asyncio.create_subprocess_exec(
                    *coordinator_ngrok_command(
                        ngrok,
                        str(context.home),
                        str(context.config_home),
                        settings.execution_lang,
                        coordinator.ingress.port,
                    ),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    env={"LANG": settings.execution_lang},
                    start_new_session=True,
                )
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as readiness_client:
                    async with asyncio.timeout(30):
                        while True:
                            if ngrok_process.returncode is not None:
                                pytest.fail("harness-owned ngrok exited before becoming ready")
                            application.raise_if_stopped()
                            try:
                                async with readiness_client.get(f"{ngrok_url.rstrip('/')}/slack/events") as response:
                                    if response.status == 405:
                                        break
                            except aiohttp.ClientError, TimeoutError:
                                pass
                            await asyncio.sleep(0.25)

                posted = await actor_slack_client.post_message(channel.channel_id, "", prompt, probe)
                candidate = None
                try:
                    async with asyncio.timeout(90):
                        while candidate is None:
                            with engine.connect() as connection:
                                candidate = (
                                    connection.execute(
                                        select(
                                            coordinator_event.c.event_id,
                                            coordinator_event.c.actor_id,
                                            coordinator_event.c.disposition,
                                        ).where(
                                            coordinator_event.c.message_id == posted.ts,
                                            coordinator_event.c.text == prompt,
                                        )
                                    )
                                    .mappings()
                                    .one_or_none()
                                )
                            if candidate is None:
                                application.raise_if_stopped()
                                await asyncio.sleep(0.25)
                except TimeoutError:
                    pytest.fail("Slack did not commit the marked E2E actor event through ngrok within 90 seconds")
                if candidate["disposition"] != "accepted":
                    pytest.fail("Slack delivered the E2E actor event, but exact probe authorization rejected it")
                assert candidate["actor_id"] == actor_auth.user_id

                evidence = None
                async with asyncio.timeout(coordinator.turn_timeout_seconds + 120):
                    while evidence is None:
                        application.raise_if_stopped()
                        with engine.connect() as connection:
                            current = (
                                connection.execute(
                                    select(
                                        coordinator_event.c.event_id,
                                        coordinator_conversation.c.id.label("conversation_id"),
                                        coordinator_conversation.c.opencode_session_id,
                                        coordinator_turn.c.id.label("turn_id"),
                                        coordinator_turn.c.assistant_message_id,
                                        coordinator_turn.c.response_text,
                                        coordinator_turn.c.state,
                                    )
                                    .select_from(
                                        coordinator_event.join(
                                            coordinator_conversation,
                                            and_(
                                                coordinator_conversation.c.provider == coordinator_event.c.provider,
                                                coordinator_conversation.c.workspace_id
                                                == coordinator_event.c.workspace_id,
                                                coordinator_conversation.c.channel_id == coordinator_event.c.channel_id,
                                                coordinator_conversation.c.thread_id == coordinator_event.c.thread_id,
                                            ),
                                        ).join(
                                            coordinator_turn,
                                            coordinator_turn.c.event_id == coordinator_event.c.event_id,
                                        )
                                    )
                                    .where(
                                        coordinator_event.c.message_id == posted.ts,
                                        coordinator_event.c.text == prompt,
                                    )
                                )
                                .mappings()
                                .one_or_none()
                            )
                        if current is not None and current["assistant_message_id"] and current["state"] == "completed":
                            evidence = current
                            break
                        evidence = None
                        await asyncio.sleep(0.25)

                with engine.connect() as connection:
                    delivery_rows = tuple(
                        connection.execute(
                            select(coordinator_delivery)
                            .where(coordinator_delivery.c.turn_id == evidence["turn_id"])
                            .order_by(coordinator_delivery.c.chunk_index)
                        ).mappings()
                    )
                provider_message_ids = frozenset(str(row["provider_message_id"]) for row in delivery_rows)
                assert provider_message_ids
                assert "" not in provider_message_ids
                delivered_replies = ()
                async with asyncio.timeout(60):
                    while not provider_message_ids or not provider_message_ids.issubset(
                        frozenset(message.ts for message in delivered_replies)
                    ):
                        pages = []
                        cursor = ""
                        while True:
                            page = await production_slack_client.replies(channel.channel_id, posted.ts, cursor)
                            pages.extend(page.messages.root)
                            cursor = page.response_metadata.next_cursor
                            if not cursor:
                                break
                        delivered_replies = tuple(pages)
                        if not provider_message_ids.issubset(frozenset(message.ts for message in delivered_replies)):
                            await asyncio.sleep(0.5)

                # THEN
                assert evidence["opencode_session_id"]
                assert evidence["assistant_message_id"]
                assert evidence["state"] == "completed"
                coordinator_answer = "".join(
                    message.text for message in delivered_replies if message.ts in provider_message_ids
                )
                assert probe in coordinator_answer
                assert "dotfiles" in coordinator_answer.lower()
                assert probe in str(evidence["response_text"])
                assert "dotfiles" in str(evidence["response_text"]).lower()
                assert len(repository.turns(int(evidence["conversation_id"]))) == 1
            finally:
                live_logger.info("Live coordinator application scope completed", probe=probe)
    finally:
        if ngrok_process is not None and ngrok_process.returncode is None:
            ngrok_process.terminate()
            try:
                await asyncio.wait_for(ngrok_process.wait(), 10)
            except TimeoutError:
                ngrok_process.kill()
                await ngrok_process.wait()
        ngrok_log_stream.write(f"probe={probe} event=ngrok_harness_stop\n".encode())
        ngrok_log_stream.close()
        live_logger.info("Live coordinator probe stopped", probe=probe)
        close()
        await actor_slack_client.close()
        await production_slack_client.close()

    with engine.connect() as connection:
        tasks_after = frozenset(
            connection.execute(
                select(task.c.id)
                .select_from(
                    task.join(task_message, task_message.c.task_id == task.c.id).join(
                        thread_message, thread_message.c.id == task_message.c.message_id
                    )
                )
                .where(thread_message.c.body.contains(probe))
            ).scalars()
        )
        jobs_after = frozenset(
            connection.execute(
                select(job.c.id).where(or_(job.c.prompt.contains(probe), job.c.title.contains(probe)))
            ).scalars()
        )
    worktrees_after = (
        frozenset(path.relative_to(config.worktree_root) for path in config.worktree_root.rglob("*"))
        if config.worktree_root.is_dir()
        else frozenset()
    )
    engine.dispose()
    assert tasks_after == tasks_before == frozenset()
    assert jobs_after == jobs_before == frozenset()
    assert worktrees_after == worktrees_before
