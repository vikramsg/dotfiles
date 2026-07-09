import fcntl
from pathlib import Path
from types import TracebackType
from typing import TextIO


class RefreshLock:
    def __init__(self, path: Path, *, blocking: bool) -> None:
        self._path = path
        self._blocking = blocking
        self._handle: TextIO | None = None
        self.acquired = False

    def __enter__(self) -> RefreshLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+")
        flags = fcntl.LOCK_EX | (0 if self._blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except BlockingIOError:
            handle.close()
            self.acquired = False
            return self
        self._handle = handle
        self.acquired = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def acquire_refresh_lock(path: Path, *, blocking: bool = False) -> RefreshLock:
    return RefreshLock(path, blocking=blocking)


def refresh_lock_in_progress(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False
