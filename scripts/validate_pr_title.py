"""Validate the repository's deliberately small PR-title convention."""

import re
import sys

SCOPES = (
    "chore",
    "ghostty",
    "git",
    "lch",
    "nvim",
    "ocint",
    "opencode",
    "screenshot",
    "terraform",
    "tmux",
    "zed",
)


def validate_pr_title(title: str) -> str | None:
    """Return an error for an invalid title, otherwise ``None``."""
    if title != title.strip():
        return "PR title must not have leading or trailing whitespace"
    if "\n" in title or "\r" in title:
        return "PR title must be one line"
    match = re.fullmatch(r"([a-z]+): ([^\s].*)", title)
    if match is None:
        return "PR title must use 'scope: non-empty summary'"
    if match.group(1) not in SCOPES:
        return f"PR title scope must be one of: {', '.join(SCOPES)}"
    return None


def main() -> int:
    title = sys.argv[1] if len(sys.argv) == 2 else ""
    error = validate_pr_title(title)
    if error is not None:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
