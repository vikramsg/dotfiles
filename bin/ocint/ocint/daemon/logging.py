import logging
import os
import stat
import time
from collections import deque
from collections.abc import Generator, Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog
from pydantic import BaseModel, ConfigDict, Field
from structlog.stdlib import BoundLogger, ProcessorFormatter
from structlog.typing import EventDict, WrappedLogger

logging.getLogger("ocint.daemon").addHandler(logging.NullHandler())


class DaemonLogSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backups: int = Field(default=5, ge=1)


class PrivateRotatingFileHandler(RotatingFileHandler):
    def doRollover(self) -> None:
        super().doRollover()
        Path(self.baseFilename).chmod(0o600)


def daemon_log_settings(home: Path, environment: Mapping[str, str]) -> DaemonLogSettings:
    state_home = Path(environment.get("XDG_STATE_HOME", home / ".local" / "state")).expanduser().resolve()
    return DaemonLogSettings(path=state_home / "ocint" / "daemon.log")


def configure(settings: DaemonLogSettings) -> None:
    _prepare_log_files(settings)
    root = logging.getLogger("ocint.daemon")
    close()
    handler = PrivateRotatingFileHandler(
        settings.path,
        maxBytes=settings.max_bytes,
        backupCount=settings.backups,
        encoding="utf-8",
    )
    handler.setFormatter(
        ProcessorFormatter(
            processor=_render_event,
            foreign_pre_chain=[
                structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
                structlog.stdlib.add_log_level,
            ],
        )
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    root.propagate = False


def close() -> None:
    root = logging.getLogger("ocint.daemon")
    for handler in tuple(root.handlers):
        handler.flush()
        handler.close()
        root.removeHandler(handler)
    root.addHandler(logging.NullHandler())


def get_logger(component: str) -> BoundLogger:
    return structlog.wrap_logger(
        logging.getLogger(f"ocint.daemon.{component}"),
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.stdlib.add_log_level,
            structlog.processors.format_exc_info,
            ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=BoundLogger,
    )


def read_log_tail(settings: DaemonLogSettings, lines: int) -> str:
    if not settings.path.is_file():
        raise RuntimeError(f"daemon log does not exist yet: {settings.path}")
    selected: deque[str] = deque(maxlen=lines)
    for path in _log_files(settings):
        try:
            with path.open(encoding="utf-8") as stream:
                selected.extend(stream)
        except OSError as error:
            raise RuntimeError(f"daemon log could not be read: {path}: {error}") from error
    return "".join(selected)


def follow_log(settings: DaemonLogSettings, lines: int) -> Generator[str]:
    initial = read_log_tail(settings, lines)
    if initial:
        yield initial
    stream = settings.path.open(encoding="utf-8")
    try:
        stream.seek(0, os.SEEK_END)
        while True:
            line = stream.readline()
            if line:
                yield line
                continue
            try:
                current = settings.path.stat()
            except FileNotFoundError:
                time.sleep(0.2)
                continue
            if current.st_ino != os.fstat(stream.fileno()).st_ino:
                stream.close()
                stream = settings.path.open(encoding="utf-8")
                continue
            time.sleep(0.2)
    finally:
        stream.close()


def _prepare_log_files(settings: DaemonLogSettings) -> None:
    path = settings.path
    directory = path.parent
    if directory.is_symlink() or (
        directory.exists() and (not directory.is_dir() or directory.stat().st_uid != os.getuid())
    ):
        raise RuntimeError(f"daemon log directory must be a user-owned regular directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    if path.is_symlink() or (
        path.exists()
        and (not path.is_file() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o600)
    ):
        raise RuntimeError(f"daemon log must be a user-owned regular mode-0600 file: {path}")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(descriptor)
    path.chmod(0o600)
    for backup in (path.with_name(f"{path.name}.{number}") for number in range(1, settings.backups + 1)):
        if os.path.lexists(backup) and (
            backup.is_symlink()
            or not backup.is_file()
            or backup.stat().st_uid != os.getuid()
            or stat.S_IMODE(backup.stat().st_mode) != 0o600
        ):
            raise RuntimeError(f"rotated daemon log must be a user-owned regular mode-0600 file: {backup}")


def _log_files(settings: DaemonLogSettings) -> tuple[Path, ...]:
    rotated = tuple(
        path
        for number in range(settings.backups, 0, -1)
        if (path := settings.path.with_name(f"{settings.path.name}.{number}")).is_file()
    )
    return (*rotated, settings.path)


def _render_event(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> str:
    values = dict(event_dict)
    timestamp = str(values.pop("timestamp", ""))
    level = str(values.pop("level", "info")).upper()
    event = _single_line(str(values.pop("event", "")))
    fields = " ".join(f"{key}={_render_value(values[key])}" for key in sorted(values))
    return f"{timestamp} {level:<5} {event}{f' {fields}' if fields else ''}"


def _render_value(value: str | int | float | bool | None) -> str:
    if isinstance(value, str):
        rendered = _single_line(value)
        quoted = rendered.replace('"', '\\"')
        return f'"{quoted}"' if not rendered or any(character.isspace() for character in rendered) else rendered
    return _single_line(str(value))


def _single_line(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")
