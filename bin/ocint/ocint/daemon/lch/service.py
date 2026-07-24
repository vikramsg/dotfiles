from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from ocint.daemon.models import OpenCodeAttachment


class InteractiveRunner(Protocol):
    def run_interactive(self, arguments: Sequence[str], environment: Mapping[str, str]) -> None: ...


def attach_to_job(
    attachment: OpenCodeAttachment,
    executable: Path,
    environment: Mapping[str, str],
    runner: InteractiveRunner,
) -> None:
    runner.run_interactive(
        (
            str(executable),
            "attach",
            attachment.server_url,
            "--dir",
            attachment.directory,
            "--session",
            attachment.session_id,
        ),
        {
            **environment,
            "OPENCODE_SERVER_USERNAME": attachment.username,
            "OPENCODE_SERVER_PASSWORD": attachment.password,
        },
    )
