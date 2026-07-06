from contextlib import AbstractContextManager, nullcontext

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from ocint._models import CliContext, CliProgress


class ClickOutput:
    def __init__(self) -> None:
        self._stderr_console = Console(stderr=True)

    def write(self, text: str, *, stderr: bool = False, nl: bool = False, enabled: bool = True) -> None:
        if enabled:
            click.echo(text, err=stderr, nl=nl)

    def progress(self, message: str, *, enabled: bool = True) -> AbstractContextManager[CliProgress]:
        if not enabled or not self._stderr_console.is_terminal:
            return nullcontext(_NoopProgress())
        return _RichProgress(message, self._stderr_console)


class _RichProgress:
    def __init__(self, message: str, console: Console) -> None:
        self._message = message
        self._console = console
        self._progress: Progress | None = None
        self._task_id: int | None = None

    def __enter__(self) -> CliProgress:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            console=self._console,
            transient=True,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(self._message, total=None)
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._progress is not None:
            self._progress.stop()

    def update(self, message: str, *, current: int | None = None, total: int | None = None) -> None:
        if self._progress is None or self._task_id is None:
            return
        self._progress.update(self._task_id, description=_progress_description(message, current=current, total=total))


class _NoopProgress:
    def update(self, message: str, *, current: int | None = None, total: int | None = None) -> None:
        pass


def default_cli_context() -> CliContext:
    return CliContext(output=ClickOutput())


def _progress_description(message: str, *, current: int | None, total: int | None) -> str:
    if current is None or total is None:
        return f"{message}..."
    return f"{message}: {current}/{total}"
