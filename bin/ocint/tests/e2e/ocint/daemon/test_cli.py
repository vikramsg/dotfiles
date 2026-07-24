import asyncio
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import pytest
import uvicorn
from aiohttp import web
from click.testing import CliRunner
from ocint.cli import main
from ocint.daemon.cli import create_daemon_app
from ocint.daemon.config import DaemonContext, DaemonSettings
from ocint.daemon.github import GitHubRepositoryPolicies, GitHubRepositoryPolicy, open_github_service
from ocint.daemon.logging import get_logger
from ocint.presentation import default_cli_context
from pydantic import SecretStr


@dataclass
class ProductionState:
    pull_requests_created: int = 0
    edited_worktree: Path | None = None
    messages: list[dict[str, object]] = field(default_factory=list)
    completion: asyncio.Event = field(default_factory=asyncio.Event)
    completion_task: asyncio.Task[None] | None = None
    prompt_returned: bool = False
    edit_after_prompt_return: bool = False


class SignalFreeServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def test_job_inspection_commands_are_exposed_only_through_lch() -> None:
    # GIVEN
    runner = CliRunner()

    # WHEN
    daemon_help = runner.invoke(main, ["daemon", "--help"])
    lch_help = runner.invoke(main, ["daemon", "lch", "--help"])

    # THEN
    assert daemon_help.exit_code == 0
    assert not {"health", "submit", "list", "status"}.intersection(
        line.strip().split(maxsplit=1)[0] for line in daemon_help.output.splitlines() if line.startswith("  ")
    )
    assert lch_help.exit_code == 0
    assert {"attach", "lifecycle", "list", "status"}.issubset(
        line.strip().split(maxsplit=1)[0] for line in lch_help.output.splitlines() if line.startswith("  ")
    )
    for description in (
        "Attach to a running job's OpenCode session.",
        "Apply existing configuration to systemd units.",
        "Show timer and service lifecycle status.",
        "List recent daemon jobs.",
        "Read or follow the daemon log.",
        "Create initial configuration and install the daemon.",
        "Show detailed status for one daemon job.",
        "Remove systemd units while preserving daemon state.",
    ):
        assert description in lch_help.output


@pytest.mark.asyncio
async def test_production_composition_completes_job_through_api(
    tmp_path: Path, unused_tcp_port_factory: Callable[[], int]
) -> None:
    # GIVEN
    api_port = unused_tcp_port_factory()
    opencode_port = unused_tcp_port_factory()
    github_port = unused_tcp_port_factory()
    state = ProductionState()

    async def opencode_health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def opencode_sessions(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response([])
        return web.json_response({"id": "session", "title": (await request.json())["title"]})

    async def opencode_messages(_request: web.Request) -> web.Response:
        return web.json_response(state.messages)

    async def opencode_prompt(request: web.Request) -> web.Response:
        worktree = Path(request.headers["x-opencode-directory"])
        prompt = (await request.json())["parts"][0]["text"]
        state.messages = [{"info": {"role": "user"}, "parts": [{"type": "text", "text": prompt}]}]

        async def complete() -> None:
            await asyncio.sleep(0.05)
            state.edit_after_prompt_return = state.prompt_returned
            (worktree / "result.txt").write_text("completed\n")
            state.edited_worktree = worktree
            state.messages.append(
                {
                    "info": {"role": "assistant", "finish": "stop"},
                    "parts": [{"type": "text", "text": "completed"}],
                }
            )
            state.completion.set()

        state.completion_task = asyncio.create_task(complete())
        state.prompt_returned = True
        return web.json_response({})

    async def opencode_status(_request: web.Request) -> web.Response:
        return web.json_response({})

    async def opencode_events(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await state.completion.wait()
        payload = f'data: {{"directory":"{state.edited_worktree}","payload":{{"type":"session.idle","properties":{{"sessionID":"session"}}}}}}\n\n'
        await response.write(payload.encode())
        await response.write_eof()
        return response

    async def github_pulls(request: web.Request) -> web.Response:
        if request.method == "GET":
            return web.json_response([])
        state.pull_requests_created += 1
        return web.json_response(
            {"number": 1, "html_url": "https://example.test/pull/1", "state": "open", "merged": False}
        )

    async def github_issues(_request: web.Request) -> web.Response:
        return web.json_response([])

    opencode_app = web.Application()
    opencode_app.router.add_get("/global/health", opencode_health)
    opencode_app.router.add_get("/session", opencode_sessions)
    opencode_app.router.add_post("/session", opencode_sessions)
    opencode_app.router.add_get("/session/{identifier}/message", opencode_messages)
    opencode_app.router.add_post("/session/{identifier}/prompt_async", opencode_prompt)
    opencode_app.router.add_get("/session/status", opencode_status)
    opencode_app.router.add_get("/global/event", opencode_events)
    opencode_runner = web.AppRunner(opencode_app)
    await opencode_runner.setup()
    await web.TCPSite(opencode_runner, "127.0.0.1", opencode_port).start()

    github_app = web.Application()
    github_app.router.add_get("/repos/owner/repo/issues", github_issues)
    github_app.router.add_get("/repos/owner/repo/pulls", github_pulls)
    github_app.router.add_post("/repos/owner/repo/pulls", github_pulls)
    github_runner = web.AppRunner(github_app)
    await github_runner.setup()
    await web.TCPSite(github_runner, "127.0.0.1", github_port).start()

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(seed), "-c", "user.name=Seed", "-c", "user.email=seed@example.test", "commit", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "origin", "main"], check=True, capture_output=True)

    transport = tmp_path / "bin"
    transport.mkdir()
    ssh = transport / "ssh"
    ssh.write_text('#!/bin/sh\nfor argument do command="$argument"; done\nexec sh -c "$command"\n')
    ssh.chmod(0o755)
    opencode = transport / "opencode"
    opencode.write_text("#!/bin/sh\nexec /bin/sleep 30\n")
    opencode.chmod(0o755)
    identity = tmp_path / "identity"
    identity.write_text("test identity\n")
    identity.chmod(0o600)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("example test-key\n")
    config = tmp_path / "daemon.toml"
    config.write_text(
        f'''database_path = "{tmp_path / "control.sqlite"}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "ssh://example{remote}"
github_repository = "owner/repo"
author_name = "Daemon Agent"
author_email = "daemon@example.test"
actors = ["allowed"]
[scheduler]
capacity = 1
job_timeout_seconds = 10
shutdown_timeout_seconds = 5
[opencode]
server_url = "http://127.0.0.1:{opencode_port}"
username = "opencode"
request_timeout_seconds = 2
expected_version = "1.17.20"
executable = "{opencode}"
config_file = "{tmp_path / "opencode.json"}"
xdg_config_home = "{tmp_path / "opencode-xdg"}"
xdg_data_home = "{tmp_path / "opencode-data"}"
[git]
ssh_executable = "{ssh}"
identity_file = "{identity}"
known_hosts_file = "{known_hosts}"
[api]
host = "127.0.0.1"
port = {api_port}
[github]
api_url = "http://127.0.0.1:{github_port}"
agent_actor = "automation-bot"
'''
    )
    settings = DaemonSettings(
        config=config,
        api_token=SecretStr("api-token"),
        github_token=SecretStr("github-token"),
        execution_path=f"{transport}:{os.environ['PATH']}",
        execution_lang="C.UTF-8",
    )
    daemon_context = DaemonContext.create(default_cli_context().output, tmp_path, os.environ, settings)
    daemon_config = daemon_context.config()
    github_manager = open_github_service(
        daemon_config.github,
        GitHubRepositoryPolicies(
            root=[
                GitHubRepositoryPolicy(
                    name=repository.name,
                    github_repository=repository.github_repository,
                    actors=repository.actors,
                )
                for repository in daemon_config.repositories
            ]
        ),
        "github-token",
        daemon_config.database_path,
    )
    github = await github_manager.__aenter__()
    application = create_daemon_app(daemon_context, github)
    app = application.app
    server = SignalFreeServer(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, log_config=None, access_log=False, lifespan="on")
    )
    daemon = asyncio.create_task(server.serve())

    # WHEN
    headers = {"Authorization": "Bearer api-token"}
    async with aiohttp.ClientSession(headers=headers) as client:
        for _attempt in range(100):
            try:
                async with client.get(f"http://127.0.0.1:{api_port}/health") as response:
                    if response.status == 200:
                        break
            except aiohttp.ClientConnectorError:
                pass
            await asyncio.sleep(0.02)
        async with client.post(
            f"http://127.0.0.1:{api_port}/api/jobs",
            json={
                "idempotency_key": "production",
                "actor": "allowed",
                "repository": "repo",
                "title": "Production change",
                "prompt": "edit",
            },
        ) as response:
            submitted = await response.json()
            assert response.status == 202
        for _attempt in range(500):
            async with client.get(f"http://127.0.0.1:{api_port}/api/jobs/{submitted['id']}") as response:
                completed = await response.json()
            if completed["state"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.02)
    server.should_exit = True
    await daemon
    await github_manager.__aexit__(None, None, None)

    # THEN
    assert completed["state"] == "completed"
    assert completed["commit_sha"]
    assert completed["pull_request_url"] == "https://example.test/pull/1"
    assert state.pull_requests_created == 1
    assert state.edited_worktree is not None
    assert state.edit_after_prompt_return
    assert state.completion_task is not None
    await state.completion_task
    remote_commit = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/ocint/{submitted['id']}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_commit == completed["commit_sha"]
    await github_runner.cleanup()
    await opencode_runner.cleanup()


@pytest.mark.asyncio
async def test_daemon_run_applies_toml_log_rotation(tmp_path: Path, unused_tcp_port_factory: Callable[[], int]) -> None:
    # GIVEN
    api_port = unused_tcp_port_factory()
    opencode_port = unused_tcp_port_factory()
    github_port = unused_tcp_port_factory()

    async def opencode_health(_request: web.Request) -> web.Response:
        return web.json_response({"healthy": True, "version": "1.17.20"})

    async def github_issues(_request: web.Request) -> web.Response:
        return web.json_response([])

    opencode_app = web.Application()
    opencode_app.router.add_get("/global/health", opencode_health)
    opencode_runner = web.AppRunner(opencode_app)
    await opencode_runner.setup()
    await web.TCPSite(opencode_runner, "127.0.0.1", opencode_port).start()

    github_app = web.Application()
    github_app.router.add_get("/repos/owner/repo/issues", github_issues)
    github_runner = web.AppRunner(github_app)
    await github_runner.setup()
    await web.TCPSite(github_runner, "127.0.0.1", github_port).start()

    executable = tmp_path / "opencode"
    executable.write_text("#!/bin/sh\nexec sleep 30\n")
    executable.chmod(0o755)
    ssh = tmp_path / "ssh"
    ssh.write_text("#!/bin/sh\nexit 0\n")
    ssh.chmod(0o755)
    identity = tmp_path / "identity"
    identity.write_text("test identity\n")
    identity.chmod(0o600)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("example.test test-key\n")
    config = tmp_path / "daemon.toml"
    state_home = tmp_path / "state"
    config.write_text(
        f'''database_path = "{tmp_path / "control.sqlite"}"
mirror_root = "{tmp_path / "mirrors"}"
worktree_root = "{tmp_path / "worktrees"}"
idle_timeout_seconds = 3
[[repositories]]
name = "repo"
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Daemon Agent"
author_email = "daemon@example.test"
[logging]
max_bytes = 1024
backup_count = 1
[opencode]
server_url = "http://127.0.0.1:{opencode_port}"
executable = "{executable}"
config_file = "{tmp_path / "opencode.json"}"
xdg_config_home = "{tmp_path / "opencode-config"}"
xdg_data_home = "{tmp_path / "opencode-data"}"
[git]
ssh_executable = "{ssh}"
identity_file = "{identity}"
known_hosts_file = "{known_hosts}"
[api]
port = {api_port}
[github]
api_url = "http://127.0.0.1:{github_port}"
agent_actor = "automation-bot"
'''
    )
    runner = CliRunner()
    log_path = state_home / "ocint" / "daemon.log"

    try:
        # WHEN
        running = asyncio.create_task(
            asyncio.to_thread(
                runner.invoke,
                main,
                ["daemon", "run"],
                env={
                    "OCINT_DAEMON_CONFIG": str(config),
                    "OCINT_DAEMON_API_TOKEN": "api-token",
                    "OCINT_DAEMON_GITHUB_TOKEN": "github-token",
                    "XDG_STATE_HOME": str(state_home),
                },
            )
        )
        for _attempt in range(250):
            log_files = (log_path, log_path.with_name("daemon.log.1"))
            if any(path.is_file() and "daemon ready" in path.read_text() for path in log_files):
                break
            if running.done():
                break
            await asyncio.sleep(0.02)
        assert not running.done()
        assert any(path.is_file() and "daemon ready" in path.read_text() for path in log_files)
        logger = get_logger("e2e")
        for sequence in range(6):
            logger.info("log rotation verification", sequence=sequence, marker="x" * 300)
        result = await running

        # THEN
        assert result.exit_code == 0, result.output
        assert log_path.is_file()
        assert log_path.with_name("daemon.log.1").is_file()
        assert not log_path.with_name("daemon.log.2").exists()
    finally:
        await github_runner.cleanup()
        await opencode_runner.cleanup()


def test_lch_setup_and_apply_are_discoverable() -> None:
    # GIVEN
    runner = CliRunner()

    # WHEN
    result = runner.invoke(main, ["daemon", "lch", "--help"])

    # THEN
    assert result.exit_code == 0
    assert "setup" in result.output
    assert "apply" in result.output
    assert "provision" not in result.output


def test_setup_reuses_existing_configuration_and_reports_applied_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN
    home = tmp_path / "home"
    config_home = home / "config"
    data_home = home / "data"
    state_home = home / "state"
    managed = config_home / "ocint"
    managed.mkdir(parents=True)
    environment_file = managed / "daemon.env"
    environment_file.write_text("OCINT_DAEMON_API_TOKEN=api\nOCINT_DAEMON_GITHUB_TOKEN=github\n")
    environment_file.chmod(0o600)
    config = managed / "daemon.toml"
    config.write_text(
        f'''database_path = "{state_home / "ocint" / "daemon.sqlite"}"
mirror_root = "{data_home / "ocint" / "mirrors"}"
worktree_root = "{data_home / "ocint" / "worktrees"}"
[[repositories]]
name = "repo"
remote_url = "git@example.test:owner/repo.git"
github_repository = "owner/repo"
author_name = "Agent"
author_email = "agent@example.test"
[lifecycle]
startup_delay_seconds = 60
inactive_interval_seconds = 600
[opencode]
executable = "{tmp_path / "opencode"}"
config_file = "{managed / "opencode.json"}"
xdg_config_home = "{managed / "opencode-xdg"}"
xdg_data_home = "{data_home / "ocint" / "opencode-data"}"
[git]
ssh_executable = "/usr/bin/ssh"
identity_file = "{tmp_path / "identity"}"
known_hosts_file = "{tmp_path / "known_hosts"}"
[github]
agent_actor = "maintainer"
'''
    )
    original = config.read_bytes()
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    executable = binary_directory / "ocint"
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"$1 $2\" = \"daemon --help\" ]; then\n"
        "  printf 'Commands:\\n  run\\n  doctor\\n  lch\\n'\n"
        "elif [ \"$1 $2 $3\" = \"daemon lch --help\" ]; then\n"
        "  printf 'Commands:\\n  apply\\n  attach\\n  lifecycle\\n  list\\n  logs\\n  setup\\n  status\\n  uninstall\\n'\n"
        "fi\n"
    )
    executable.chmod(0o755)
    loginctl = binary_directory / "loginctl"
    loginctl.write_text("#!/bin/sh\nprintf 'yes\\n'\n")
    loginctl.chmod(0o755)
    systemctl = binary_directory / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary_directory))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    # WHEN
    result = CliRunner().invoke(main, ["daemon", "lch", "setup"])

    # THEN
    assert result.exit_code == 0, result.output
    assert config.read_bytes() == original
    assert f"Configuration: reused; path={config}; modified=no" in result.output
    assert f"Environment: reused; path={environment_file}; modified=no" in result.output
    assert "Systemd service: regenerated;" in result.output
    assert f"executable={executable.resolve()}" in result.output
    assert "Systemd timer: enabled;" in result.output
    assert "inactive_interval_seconds=600" in result.output
    assert "OpenCode configuration: reused;" in result.output


def test_setup_rejects_incompatible_path_binary_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # GIVEN
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    executable = binary_directory / "ocint"
    executable.write_text("#!/bin/sh\nprintf 'Commands:\\n  config\\n'\n")
    executable.chmod(0o755)
    config_home = tmp_path / "xdg-config"
    monkeypatch.setenv("PATH", str(binary_directory))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    runner = CliRunner()

    # WHEN
    result = runner.invoke(main, ["daemon", "lch", "setup"])

    # THEN
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "does not expose daemon run, doctor, and lch" in str(result.exception)
    assert not (config_home / "ocint").exists()
