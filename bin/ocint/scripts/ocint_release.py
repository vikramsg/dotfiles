"""Prepare and locally publish safe ocint releases.

This is repository automation, deliberately not an installed ocint command.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class ReleaseError(RuntimeError):
    """A release precondition failed without changing release state."""


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> SemVer:
        match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
        if match is None:
            raise ReleaseError(f"Expected a stable SemVer (X.Y.Z), got: {value}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class Commit:
    oid: str
    timestamp: int
    subject: str


@dataclass(frozen=True)
class ReleasePaths:
    root: Path

    @property
    def pyproject(self) -> Path:
        return self.root / "bin" / "ocint" / "pyproject.toml"

    @property
    def changelog(self) -> Path:
        return self.root / "bin" / "ocint" / "CHANGELOG.md"

    @property
    def lock(self) -> Path:
        return self.root / "uv.lock"

    @property
    def relative_files(self) -> tuple[str, str, str]:
        return ("bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock")


def run(command: list[str], *, cwd: Path, capture: bool = True) -> str:
    """Run a subprocess without a shell and turn failures into release errors."""
    try:
        result = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or error.stdout or "").strip()
        raise ReleaseError(f"Command failed: {' '.join(command)}{f': {detail}' if detail else ''}") from error
    return result.stdout.strip() if capture else ""


def git(root: Path, *arguments: str) -> str:
    return run(["git", *arguments], cwd=root)


def project_version(source: str) -> SemVer:
    try:
        value = tomllib.loads(source)["project"]["version"]
    except (KeyError, tomllib.TOMLDecodeError) as error:
        raise ReleaseError("Cannot read project.version from bin/ocint/pyproject.toml") from error
    if not isinstance(value, str):
        raise ReleaseError("ocint project.version must be a string")
    return SemVer.parse(value)


def file_version(path: Path) -> SemVer:
    return project_version(path.read_text())


def lock_version(path: Path) -> SemVer:
    try:
        packages = tomllib.loads(path.read_text())["package"]
        value = next(item["version"] for item in packages if item.get("name") == "ocint")
    except (KeyError, StopIteration, tomllib.TOMLDecodeError) as error:
        raise ReleaseError("uv.lock does not contain the ocint package version") from error
    if not isinstance(value, str):
        raise ReleaseError("The ocint uv.lock version must be a string")
    return SemVer.parse(value)


def latest_annotated_tag(root: Path, revision: str = "HEAD") -> tuple[str, SemVer]:
    tags = git(root, "tag", "--merged", revision, "--list", "ocint-v*").splitlines()
    versions: list[tuple[SemVer, str]] = []
    for tag in tags:
        try:
            version = SemVer.parse(tag.removeprefix("ocint-v"))
        except ReleaseError:
            continue
        if git(root, "cat-file", "-t", tag) != "tag":
            raise ReleaseError(f"Release tag must be annotated: {tag}")
        versions.append((version, tag))
    if not versions:
        raise ReleaseError("No reachable annotated ocint-v* release tag exists")
    version, tag = max(versions)
    return tag, version


def version_at_tag(root: Path, tag: str) -> SemVer:
    source = git(root, "show", f"{tag}:bin/ocint/pyproject.toml")
    return project_version(source)


def parse_ocint_commit(oid: str, timestamp: int, subject: str) -> Commit | None:
    if subject.startswith("ocint: ") and subject.removeprefix("ocint: ").strip():
        return Commit(oid=oid, timestamp=timestamp, subject=subject.removeprefix("ocint: "))
    if subject.lower().startswith("ocint"):
        raise ReleaseError(f"Malformed ocint commit prefix: {subject}")
    return None


def collect_ocint_commits(root: Path, start: str, end: str = "HEAD") -> list[Commit]:
    output = git(root, "log", "--format=%H%x1f%ct%x1f%s", f"{start}..{end}")
    commits: list[Commit] = []
    for line in output.splitlines():
        oid, timestamp, subject = line.split("\x1f", 2)
        commit = parse_ocint_commit(oid, int(timestamp), subject)
        if commit is not None:
            commits.append(commit)
    if not commits:
        raise ReleaseError(f"No valid 'ocint: ' commits exist after {start}")
    return commits


def changelog_section(version: SemVer, commits: list[Commit]) -> str:
    lines = [f"## {version}", ""]
    for commit in sorted(commits, key=lambda item: (-item.timestamp, item.oid)):
        date = datetime.fromtimestamp(commit.timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines.append(f"- {date} {commit.subject} ({commit.oid[:10]})")
    return "\n".join(lines) + "\n"


def updated_changelog(existing: str, version: SemVer, commits: list[Commit]) -> str:
    section = changelog_section(version, commits)
    if not existing:
        return f"# ocint changelog\n\n{section}"
    if not existing.startswith("# ocint changelog\n"):
        raise ReleaseError("Existing ocint changelog has an unexpected heading")
    return f"# ocint changelog\n\n{section}\n{existing.removeprefix('# ocint changelog\n').lstrip()}"


def changed_files(root: Path) -> set[str]:
    raw = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return {line[3:] for line in raw.splitlines() if line}


def validate_repository(root: Path) -> None:
    actual = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual != root.resolve() or not (root / "bin" / "ocint" / "pyproject.toml").is_file():
        raise ReleaseError(f"Not the expected dotfiles repository: {root}")
    if git(root, "branch", "--show-current") != "main":
        raise ReleaseError("ocint releases must run on the main branch")
    try:
        origin_main = git(root, "rev-parse", "origin/main")
    except ReleaseError as error:
        raise ReleaseError("Locally known origin/main is required; fetch it before releasing") from error
    if git(root, "rev-parse", "HEAD") != origin_main:
        raise ReleaseError("Local main must exactly equal locally known origin/main")


def validate_versions(paths: ReleasePaths, requested: SemVer, tag: str, tagged: SemVer) -> None:
    current = file_version(paths.pyproject)
    if current != tagged:
        raise ReleaseError(f"Current package version {current} differs from {tag} version {tagged}")
    if requested <= current:
        raise ReleaseError(f"Requested version {requested} must be greater than current version {current}")


def validate_consistency(paths: ReleasePaths, version: SemVer) -> None:
    if file_version(paths.pyproject) != version or lock_version(paths.lock) != version:
        raise ReleaseError(f"pyproject.toml and uv.lock must both contain ocint {version}")


def run_checks(paths: ReleasePaths) -> None:
    run(["uv", "lock", "--check"], cwd=paths.root, capture=False)
    for recipe in ("test", "check", "smoke"):
        run(["just", "--justfile", str(paths.root / "bin" / "ocint" / "justfile"), recipe], cwd=paths.root, capture=False)


def _snapshots(paths: ReleasePaths) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in (paths.pyproject, paths.changelog, paths.lock)}


def _restore(snapshots: dict[Path, bytes | None]) -> None:
    for path, content in snapshots.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)


def prepare(root: Path, requested: SemVer) -> None:
    paths = ReleasePaths(root)
    validate_repository(root)
    tag, tagged = latest_annotated_tag(root)
    commits = collect_ocint_commits(root, tag)
    tagged_changelog = (
        git(root, "show", f"{tag}:bin/ocint/CHANGELOG.md")
        if _git_path_exists(root, tag, "bin/ocint/CHANGELOG.md")
        else ""
    )
    expected_changelog = updated_changelog(tagged_changelog, requested, commits)
    changes = changed_files(root)
    if changes:
        if changes != set(paths.relative_files):
            raise ReleaseError(f"Worktree is not clean; unexpected changes: {', '.join(sorted(changes))}")
        validate_consistency(paths, requested)
        if paths.changelog.read_text() != expected_changelog:
            raise ReleaseError("Existing prepared changelog does not match release history")
        print(f"ocint {requested} is already prepared")
        return
    validate_versions(paths, requested, tag, tagged)
    snapshots = _snapshots(paths)
    try:
        run(
            ["uv", "version", "--directory", str(root), "--package", "ocint", str(requested)],
            cwd=root,
            capture=False,
        )
        paths.changelog.write_text(expected_changelog)
        validate_consistency(paths, requested)
        if changed_files(root) != set(paths.relative_files):
            raise ReleaseError("Prepare must change only pyproject.toml, CHANGELOG.md, and uv.lock")
        run_checks(paths)
    except BaseException:
        _restore(snapshots)
        raise
    print(f"Prepared ocint {requested}; review the three changed files, then publish")


def _release_commit_state(paths: ReleasePaths, version: SemVer) -> tuple[bool, str]:
    subject = f"ocint: Release v{version}"
    if git(paths.root, "log", "-1", "--format=%s") != subject:
        return False, git(paths.root, "rev-parse", "HEAD")
    if git(paths.root, "rev-parse", "HEAD^") != git(paths.root, "rev-parse", "origin/main"):
        raise ReleaseError("Release commit parent is not locally known origin/main")
    files = set(git(paths.root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines())
    if files != set(paths.relative_files):
        raise ReleaseError("Release commit does not contain exactly the three release files")
    return True, git(paths.root, "rev-parse", "HEAD^")


def _validate_publish_content(paths: ReleasePaths, version: SemVer, history_end: str) -> str:
    validate_consistency(paths, version)
    tag, tagged = latest_annotated_tag(paths.root, history_end)
    if tagged >= version or version_at_tag(paths.root, tag) != tagged:
        raise ReleaseError("Requested publish version conflicts with release tag history")
    commits = collect_ocint_commits(paths.root, tag, history_end)
    old = git(paths.root, "show", f"{tag}:bin/ocint/CHANGELOG.md") if _git_path_exists(paths.root, tag, "bin/ocint/CHANGELOG.md") else ""
    expected = updated_changelog(old, version, commits)
    if paths.changelog.read_text() != expected:
        raise ReleaseError("Prepared changelog does not exactly match release history")
    return tag


def _git_path_exists(root: Path, revision: str, path: str) -> bool:
    result = subprocess.run(["git", "cat-file", "-e", f"{revision}:{path}"], cwd=root, capture_output=True)
    return result.returncode == 0


def _install_and_verify(paths: ReleasePaths, version: SemVer) -> None:
    run(["uv", "tool", "install", str(paths.root / "bin" / "ocint"), "--force", "--no-cache"], cwd=paths.root, capture=False)
    configured_bin = os.environ.get("UV_TOOL_BIN_DIR")
    executable = Path(configured_bin) / "ocint" if configured_bin else Path(shutil.which("ocint") or "ocint")
    output = run([str(executable), "--version"], cwd=paths.root)
    if output != f"ocint {version}":
        raise ReleaseError(f"Installed version check failed: {output!r}")


def publish(root: Path, version: SemVer, *, yes: bool) -> None:
    paths = ReleasePaths(root)
    actual = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual != root.resolve() or git(root, "branch", "--show-current") != "main":
        raise ReleaseError("Publish must run at the expected repository root on main")
    committed, history_end = _release_commit_state(paths, version)
    if not committed and history_end != git(root, "rev-parse", "origin/main"):
        raise ReleaseError("Prepared release HEAD must exactly equal locally known origin/main")
    changes = changed_files(root)
    if committed:
        if changes:
            raise ReleaseError("Recovery requires a clean worktree after the release commit")
    elif changes != set(paths.relative_files):
        raise ReleaseError("Publish requires exactly the three prepared release changes")
    _validate_publish_content(paths, version, history_end)
    tag_name = f"ocint-v{version}"
    existing_tag = git(root, "tag", "--list", tag_name)
    if existing_tag:
        if not committed or git(root, "cat-file", "-t", tag_name) != "tag":
            raise ReleaseError(f"Conflicting tag exists: {tag_name}")
        if git(root, "rev-list", "-n", "1", tag_name) != git(root, "rev-parse", "HEAD"):
            raise ReleaseError(f"Tag {tag_name} does not target the release commit")
    if not yes:
        response = input(f"Commit, tag, and install ocint {version} locally? [y/N] ")
        if response.lower() not in {"y", "yes"}:
            raise ReleaseError("Publish cancelled")
    run_checks(paths)
    if not committed:
        run(["git", "add", "--", *paths.relative_files], cwd=root)
        run(["git", "commit", "-m", f"ocint: Release v{version}"], cwd=root, capture=False)
    if not existing_tag:
        run(["git", "tag", "-a", tag_name, "-m", f"ocint v{version}"], cwd=root)
    _install_and_verify(paths, version)
    print(f"Published ocint {version} locally; no remote refs or GitHub releases were changed")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Prepare or locally publish an ocint stable release")
    result.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3], help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="update exactly the version, changelog, and lock file")
    prepare_parser.add_argument("version")
    publish_parser = commands.add_parser("publish", help="commit, annotate-tag, install, and verify a prepared release")
    publish_parser.add_argument("version")
    publish_parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    return result


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        version = SemVer.parse(args.version)
        if args.command == "prepare":
            prepare(args.root.resolve(), version)
        else:
            publish(args.root.resolve(), version, yes=args.yes)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
