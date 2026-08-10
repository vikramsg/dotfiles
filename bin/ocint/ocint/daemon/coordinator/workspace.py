import json
import os
import stat
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from ocint.daemon.coordinator.config import CoordinatorWorkspaceConfig


class CoordinatorWorkspace:
    def __init__(self, config: CoordinatorWorkspaceConfig) -> None:
        self.config = config

    def generate(self) -> None:
        directory_fd = self._open_private_directory(self.config.root)
        try:
            self._atomic_write(directory_fd, "AGENTS.md", self._agents().encode())
            catalogue = {
                "repositories": [repository.model_dump(mode="json") for repository in self.config.repositories]
            }
            body = (json.dumps(catalogue, indent=2, sort_keys=True) + "\n").encode()
            self._atomic_write(directory_fd, "repositories.json", body)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _open_private_directory(path: Path) -> int:
        absolute = path.expanduser().absolute()
        current = Path(absolute.anchor)
        descriptor = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in absolute.parts[1:]:
                current /= component
                try:
                    child_descriptor = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    with suppress(FileExistsError):
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    try:
                        child_descriptor = os.open(
                            component,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                    except OSError as error:
                        CoordinatorWorkspace._raise_unsafe_component(descriptor, component, current, error)
                except OSError as error:
                    CoordinatorWorkspace._raise_unsafe_component(descriptor, component, current, error)
                os.close(descriptor)
                descriptor = child_descriptor
            information = os.fstat(descriptor)
            if information.st_uid != os.getuid():
                raise PermissionError(f"coordinator workspace is not owned by the current user: {absolute}")
            os.fchmod(descriptor, 0o700)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _raise_unsafe_component(parent_fd: int, component: str, path: Path, error: OSError) -> None:
        try:
            information = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise error from None
        if stat.S_ISLNK(information.st_mode):
            raise ValueError(f"coordinator workspace path contains a symlink: {path}") from error
        if not stat.S_ISDIR(information.st_mode):
            raise ValueError(f"coordinator workspace path is not a directory: {path}") from error
        raise error

    @staticmethod
    def _atomic_write(directory_fd: int, name: str, body: bytes) -> None:
        try:
            existing = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise ValueError(f"coordinator workspace target is not a regular file: {name}")
            if existing.st_uid != os.getuid():
                raise PermissionError(f"coordinator workspace target is not owned by the current user: {name}")
        except FileNotFoundError:
            pass
        temporary = f".{name}.{uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        try:
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
                raise ValueError(f"coordinator workspace target changed type: {name}")
            if current.st_uid != os.getuid():
                raise PermissionError(f"coordinator workspace target changed owner: {name}")
        except FileNotFoundError:
            pass
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.chmod(name, 0o600, dir_fd=directory_fd, follow_symlinks=False)

    @staticmethod
    def _agents() -> str:
        return """# Coordinator

You are the sole conversational coordinator for Slack.

- Answer questions concisely in plain text suitable for Slack.
- Use web research when it helps.
- Read `repositories.json` only as a safe catalogue of available repositories.
- Do not inspect, modify, or run commands in target repositories.
- Do not claim repository work has been completed.
- When repository work is needed, name the likely repository and objective, and state that repository execution is not available yet.
- Ask follow-up questions in the response; do not use an interactive question tool.
"""
