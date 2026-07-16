import asyncio
import getpass
import json
import uuid
from collections.abc import Mapping
from pathlib import Path

import aiohttp
import click

from ocint._models import CliContext
from ocint.daemon.composition import run_daemon
from ocint.daemon.config import DaemonSettings, load_daemon_config
from ocint.daemon.db import current_daemon_head_revision, migrate_daemon_db
from ocint.daemon.models import WorkRequest, WorkSource


@click.group()
def daemon() -> None:
    """Run and control the durable OpenCode orchestration daemon."""


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
    rendered = loaded.config.model_dump_json(indent=2)
    context.output.write(json.dumps({"config_path": str(path), "effective": json.loads(rendered)}, indent=2), nl=True)


@daemon.command("migrate")
@click.pass_obj
def migrate_command(context: CliContext) -> None:
    loaded = load_daemon_config(DaemonSettings(), Path.home())
    migrate_daemon_db(loaded.config.database_path)
    context.output.write(current_daemon_head_revision(), nl=True)


@daemon.command("run")
def run_command() -> None:
    """Run the scheduler and authenticated API in the foreground."""
    asyncio.run(run_daemon(DaemonSettings(), Path.home(), []))


@daemon.command("reload")
@click.pass_obj
def reload_command(context: CliContext) -> None:
    context.output.write(asyncio.run(_request("POST", "/api/reload")), nl=True)


@daemon.command("submit")
@click.argument("repository")
@click.argument("text")
@click.option("actor", "--actor", default="", help="Authorized actor; defaults to the local user.")
@click.option("conversation", "--conversation", default="")
@click.option("key", "--idempotency-key", default="")
@click.pass_obj
def submit_command(context: CliContext, repository: str, text: str, actor: str, conversation: str, key: str) -> None:
    identifier = key or uuid.uuid4().hex
    request = WorkRequest(
        idempotency_key=identifier,
        conversation_id=conversation or f"manual:{identifier}",
        actor=actor or getpass.getuser(),
        repository=repository,
        text=text,
        source=WorkSource.MANUAL,
        delivery_adapter="control",
        delivery_target="manual",
    )
    context.output.write(asyncio.run(_request("POST", "/api/jobs", request.model_dump(mode="json"))), nl=True)


@daemon.command("status")
@click.argument("job_id", required=False)
@click.pass_obj
def status_command(context: CliContext, job_id: str | None) -> None:
    path = f"/api/jobs/{job_id}" if job_id else "/api/jobs"
    context.output.write(asyncio.run(_request("GET", path)), nl=True)


async def _request(method: str, path: str, payload: Mapping[str, str] | None = None) -> str:
    loaded = load_daemon_config(DaemonSettings(), Path.home())
    token = loaded.settings.api_token.get_secret_value()
    if not token:
        raise click.ClickException("OCINT_DAEMON_API_TOKEN is required")
    base = f"http://{loaded.config.api.host}:{loaded.config.api.port}"
    async with (
        aiohttp.ClientSession(headers={"Authorization": f"Bearer {token}"}) as client,
        client.request(method, f"{base}{path}", json=payload) as response,
    ):
        body = await response.text()
        if response.status >= 400:
            raise click.ClickException(f"daemon HTTP {response.status}: {body}")
        return body
