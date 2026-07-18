from typing import Protocol


class LogRotation(Protocol):
    @property
    def max_bytes(self) -> int: ...

    @property
    def backup_count(self) -> int: ...
