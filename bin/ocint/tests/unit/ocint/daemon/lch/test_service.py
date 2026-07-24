from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ocint.daemon.lch.service import attach_to_job
from ocint.daemon.models import OpenCodeAttachment


@dataclass
class RecordingRunner:
    arguments: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)

    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
        self.arguments = list(arguments)
        self.environment = dict(environment)


def test_attach_uses_job_session_and_keeps_credentials_out_of_arguments(tmp_path: Path) -> None:
    # GIVEN
    runner = RecordingRunner()
    attachment = OpenCodeAttachment(
        server_url="http://127.0.0.1:4097",
        username="daemon-user",
        password="ephemeral-secret",
        directory=str(tmp_path / "worktree"),
        session_id="session-1",
    )

    # WHEN
    attach_to_job(attachment, tmp_path / "opencode", {"TERM": "xterm"}, runner)

    # THEN
    assert runner.arguments == [
        str(tmp_path / "opencode"),
        "attach",
        "http://127.0.0.1:4097",
        "--dir",
        str(tmp_path / "worktree"),
        "--session",
        "session-1",
    ]
    assert "ephemeral-secret" not in runner.arguments
    assert runner.environment == {
        "TERM": "xterm",
        "OPENCODE_SERVER_USERNAME": "daemon-user",
        "OPENCODE_SERVER_PASSWORD": "ephemeral-secret",
    }
