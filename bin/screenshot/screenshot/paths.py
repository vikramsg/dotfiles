import os
import re
from pathlib import Path


_SHELL_UNSAFE_CHARS = re.compile(r"([^A-Za-z0-9_./~-])")


def get_home_directory() -> Path:
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser().resolve()


def to_home_relative_path(path: str | Path) -> str:
    resolved_path = Path(path).expanduser().resolve()
    home_directory = get_home_directory()

    try:
        relative_path = resolved_path.relative_to(home_directory)
    except ValueError:
        return str(resolved_path)

    if relative_path == Path("."):
        return "~"

    return f"~/{relative_path.as_posix()}"


def escape_shell_path(path: str | Path) -> str:
    return _SHELL_UNSAFE_CHARS.sub(r"\\\1", str(path))


def format_user_path(path: str | Path) -> str:
    return escape_shell_path(to_home_relative_path(path))
