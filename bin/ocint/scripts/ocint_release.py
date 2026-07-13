"""Prepare PR-only ocint releases and create release tags in CI."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


class ReleaseError(RuntimeError):
    """A release invariant was not satisfied."""


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
class ReleasePolicy:
    files: tuple[str, str, str]
    baseline_version: SemVer
    baseline_commit: str
    baseline_confirmation: str

    def branch(self, version: SemVer) -> str:
        return f"ocint-release/v{version}"

    def title(self, version: SemVer) -> str:
        return f"ocint: Release v{version}"

    def tag(self, version: SemVer) -> str:
        return f"ocint-v{version}"


@dataclass(frozen=True)
class ReleasePaths:
    root: Path
    policy: ReleasePolicy

    @property
    def pyproject(self) -> Path:
        return self.root / self.policy.files[0]

    @property
    def changelog(self) -> Path:
        return self.root / self.policy.files[1]

    @property
    def lock(self) -> Path:
        return self.root / self.policy.files[2]


@dataclass(frozen=True)
class CiContext:
    actions: str
    event_name: str
    ref: str
    sha: str


def release_policy() -> ReleasePolicy:
    return ReleasePolicy(
        files=("bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"),
        baseline_version=SemVer(0, 1, 0),
        baseline_commit="8e13c509ec1b31a6f97501ef3f0215a4bdb58a8e",
        baseline_confirmation="create ocint-v0.1.0 baseline tag",
    )


def ci_context() -> CiContext:
    return CiContext(
        actions=os.environ.get("GITHUB_ACTIONS", ""),
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
        ref=os.environ.get("GITHUB_REF", ""),
        sha=os.environ.get("GITHUB_SHA", ""),
    )


def run(command: list[str], *, cwd: Path, capture: bool = True) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = ""
        if isinstance(error, subprocess.CalledProcessError):
            detail = (error.stderr or error.stdout or "").strip()
        raise ReleaseError(f"Command failed: {' '.join(command)}{f': {detail}' if detail else ''}") from error
    return result.stdout.rstrip("\n") if capture else ""


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


def parse_release_title(subject: str) -> SemVer:
    match = re.fullmatch(r"ocint: Release v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?: \(#[1-9]\d*\))?", subject)
    if match is None:
        raise ReleaseError(f"Expected release title 'ocint: Release vX.Y.Z', got: {subject}")
    return SemVer(*(int(part) for part in match.groups()))


def parse_pr_title(title: str) -> SemVer:
    match = re.fullmatch(r"ocint: Release v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", title)
    if match is None:
        raise ReleaseError(f"Expected release title 'ocint: Release vX.Y.Z', got: {title}")
    return SemVer(*(int(part) for part in match.groups()))


def parse_ocint_commit(subject: str) -> str | None:
    if subject.startswith("ocint: ") and subject.removeprefix("ocint: ").strip():
        return subject.removeprefix("ocint: ")
    if subject.lower().startswith("ocint"):
        raise ReleaseError(f"Malformed ocint commit prefix: {subject}")
    return None


def changelog_section(version: SemVer, commits: list[str], release_date: date) -> str:
    return "\n".join([f"## {version} - {release_date.isoformat()}", "", *(f"- {item}" for item in commits)]) + "\n"


def updated_changelog(existing: str, version: SemVer, commits: list[str], release_date: date) -> str:
    heading = "# Changelog\n\n"
    section = changelog_section(version, commits, release_date)
    if not existing:
        return f"{heading}{section}"
    if not existing.startswith(heading):
        raise ReleaseError("Existing ocint changelog has an unexpected heading")
    return f"{heading}{section}\n{existing.removeprefix(heading)}"


def prepared_release_date(changelog: str, version: SemVer) -> date:
    match = re.match(rf"# Changelog\n\n## {re.escape(str(version))} - (\d{{4}}-\d{{2}}-\d{{2}})\n\n", changelog)
    if match is None:
        raise ReleaseError(f"Prepared changelog is missing the dated {version} release heading")
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as error:
        raise ReleaseError(f"Prepared changelog has an invalid release date: {match.group(1)}") from error


def parse_porcelain_status(raw: bytes) -> set[str]:
    changes: set[str] = set()
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            raise ReleaseError("Unexpected Git porcelain status entry")
        if b"R" in entry[:2] or b"C" in entry[:2]:
            raise ReleaseError("Renamed or copied paths are not valid release changes")
        changes.add(os.fsdecode(entry[3:]))
    return changes


def changed_files(root: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReleaseError("Unable to inspect the Git worktree") from error
    return parse_porcelain_status(result.stdout)


def validate_root(paths: ReleasePaths) -> None:
    actual = Path(git(paths.root, "rev-parse", "--show-toplevel")).resolve()
    if actual != paths.root.resolve() or not paths.pyproject.is_file():
        raise ReleaseError(f"Not the expected dotfiles repository: {paths.root}")


def latest_annotated_tag(root: Path, revision: str) -> tuple[str, SemVer]:
    versions: list[tuple[SemVer, str]] = []
    for tag in git(root, "tag", "--merged", revision, "--list", "ocint-v*").splitlines():
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


def git_path_exists(root: Path, revision: str, path: str) -> bool:
    git(root, "cat-file", "-e", f"{revision}^{{commit}}")
    return path in git(root, "ls-tree", "-z", "--name-only", revision, "--", path).split("\0")


def release_commits(root: Path, tag: str, end: str) -> list[str]:
    commits = [
        parsed
        for subject in git(root, "log", "--format=%s", f"{tag}..{end}").splitlines()
        if (parsed := parse_ocint_commit(subject)) is not None
    ]
    if not commits:
        raise ReleaseError(f"No valid 'ocint: ' commits exist after {tag}")
    return commits


def validate_release_content(paths: ReleasePaths, version: SemVer, history_end: str) -> None:
    if file_version(paths.pyproject) != version or lock_version(paths.lock) != version:
        raise ReleaseError(f"pyproject.toml and uv.lock must both contain ocint {version}")
    tag, tagged = latest_annotated_tag(paths.root, history_end)
    tagged_source = git(paths.root, "show", f"{tag}:{paths.policy.files[0]}")
    if project_version(tagged_source) != tagged:
        raise ReleaseError(f"Tag {tag} does not contain package version {tagged}")
    if version <= tagged:
        raise ReleaseError(f"Requested version {version} must be greater than current version {tagged}")
    previous = (
        git(paths.root, "show", f"{tag}:{paths.policy.files[1]}")
        if git_path_exists(paths.root, tag, paths.policy.files[1])
        else ""
    )
    actual = paths.changelog.read_text()
    expected = updated_changelog(
        previous,
        version,
        release_commits(paths.root, tag, history_end),
        prepared_release_date(actual, version),
    )
    if actual != expected:
        raise ReleaseError("Prepared changelog does not exactly match release history")


def run_checks(paths: ReleasePaths) -> None:
    run(["uv", "lock", "--check"], cwd=paths.root, capture=False)
    for recipe in ("test", "check", "smoke"):
        run(["just", "--justfile", str(paths.root / "bin/ocint/justfile"), recipe], cwd=paths.root, capture=False)


def prepare(root: Path, version: SemVer, policy: ReleasePolicy) -> None:
    paths = ReleasePaths(root, policy)
    validate_root(paths)
    branch = git(root, "branch", "--show-current")
    if branch != policy.branch(version):
        raise ReleaseError(f"Prepare must run on branch {policy.branch(version)}")
    try:
        base = git(root, "rev-parse", "origin/main")
    except ReleaseError as error:
        raise ReleaseError("Locally known origin/main is required; fetch it before preparing") from error
    if git(root, "rev-parse", "HEAD") != base:
        raise ReleaseError("Release branch HEAD must exactly equal locally known origin/main")
    changes = changed_files(root)
    if changes and changes != set(policy.files):
        raise ReleaseError(f"Worktree is not clean; unexpected changes: {', '.join(sorted(changes))}")
    if changes:
        validate_release_content(paths, version, base)
        print(f"ocint {version} is already prepared")
        return
    tag, tagged = latest_annotated_tag(root, base)
    if project_version(git(root, "show", f"{tag}:{policy.files[0]}")) != tagged:
        raise ReleaseError(f"Tag {tag} does not contain package version {tagged}")
    current = file_version(paths.pyproject)
    if current != tagged:
        raise ReleaseError(f"Current package version {current} differs from {tag} version {tagged}")
    if version <= current:
        raise ReleaseError(f"Requested version {version} must be greater than current version {current}")
    previous = git(root, "show", f"{tag}:{policy.files[1]}") if git_path_exists(root, tag, policy.files[1]) else ""
    expected = updated_changelog(previous, version, release_commits(root, tag, base), datetime.now(UTC).date())
    snapshots = {
        path: path.read_bytes() if path.exists() else None for path in (paths.pyproject, paths.changelog, paths.lock)
    }
    try:
        run(["uv", "version", "--directory", str(root), "--package", "ocint", str(version)], cwd=root, capture=False)
        paths.changelog.write_text(expected)
        if changed_files(root) != set(policy.files):
            raise ReleaseError("Prepare must change exactly pyproject.toml, CHANGELOG.md, and uv.lock")
        validate_release_content(paths, version, base)
        run_checks(paths)
    except BaseException:
        for path, content in snapshots.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    print(f"Prepared ocint {version}; review and submit the release branch through a pull request")


def release_candidate(
    policy: ReleasePolicy,
    *,
    branch: str,
    title: str,
    files: set[str],
    base_version: SemVer,
    head_version: SemVer,
) -> bool:
    return (
        branch.startswith("ocint-release/")
        or re.match(r"(?i)^ocint:\s*release\b", title) is not None
        or policy.files[1] in files
        or base_version != head_version
    )


def validate_pr(
    root: Path,
    base: str,
    base_ref: str,
    title: str,
    branch: str,
    policy: ReleasePolicy,
) -> None:
    paths = ReleasePaths(root, policy)
    validate_root(paths)
    if base_ref != "main":
        raise ReleaseError("Release PR validation requires base ref main")
    git(root, "cat-file", "-e", f"{base}^{{commit}}")
    files = set(git(root, "diff", "--name-only", f"{base}...HEAD").splitlines())
    base_version = project_version(git(root, "show", f"{base}:{policy.files[0]}"))
    head_version = file_version(paths.pyproject)
    if not release_candidate(
        policy,
        branch=branch,
        title=title,
        files=files,
        base_version=base_version,
        head_version=head_version,
    ):
        print("Not an ocint release PR; validation is not applicable")
        return
    version = parse_pr_title(title)
    if title != policy.title(version):
        raise ReleaseError(f"Release PR title must be exactly: {policy.title(version)}")
    if branch != policy.branch(version):
        raise ReleaseError(f"Release PR branch must be exactly: {policy.branch(version)}")
    if git(root, "merge-base", base, "HEAD") != git(root, "rev-parse", base):
        raise ReleaseError("Release PR base must be an ancestor of HEAD")
    if files != set(policy.files):
        raise ReleaseError("Release PR must change exactly the three release files")
    if changed_files(root):
        raise ReleaseError("Release PR validation requires a clean worktree")
    validate_release_content(paths, version, base)
    print(f"Validated release PR for ocint {version}")


def require_ci(root: Path, context: CiContext, event_name: str) -> str:
    if context.actions != "true":
        raise ReleaseError("Tag creation requires GITHUB_ACTIONS=true")
    if context.event_name != event_name:
        raise ReleaseError(f"Tag creation requires GITHUB_EVENT_NAME={event_name}")
    if context.ref != "refs/heads/main":
        raise ReleaseError("Tag creation requires GITHUB_REF=refs/heads/main")
    head = git(root, "rev-parse", "HEAD")
    if context.sha != head:
        raise ReleaseError("GITHUB_SHA must equal the checked-out HEAD")
    return head


def ensure_tag(root: Path, tag: str, target: str) -> bool:
    if git(root, "tag", "--list", tag):
        if git(root, "cat-file", "-t", tag) != "tag" or git(root, "rev-list", "-n", "1", tag) != target:
            raise ReleaseError(f"Conflicting tag exists: {tag}")
        return False
    return True


def create_ci_tag(root: Path, tag: str, target: str, message: str) -> None:
    run(
        [
            "git",
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "tag",
            "-a",
            tag,
            target,
            "-m",
            message,
        ],
        cwd=root,
    )


def ci_tag(root: Path, policy: ReleasePolicy, context: CiContext) -> None:
    paths = ReleasePaths(root, policy)
    validate_root(paths)
    head = require_ci(root, context, "push")
    subject = git(root, "log", "-1", "--format=%s")
    version = parse_release_title(subject)
    parent_line = git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(parent_line) != 2:
        raise ReleaseError("A release squash commit must have exactly one parent")
    parent = parent_line[1]
    files = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", parent, head).splitlines())
    if files != set(policy.files):
        raise ReleaseError("Merged release commit must change exactly the three release files")
    if changed_files(root):
        raise ReleaseError("CI tag creation requires a clean worktree")
    tag = policy.tag(version)
    should_create = ensure_tag(root, tag, head)
    validate_release_content(paths, version, parent)
    if should_create:
        create_ci_tag(root, tag, head, f"ocint v{version}")
    run(["git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}"], cwd=root, capture=False)
    print(f"Ensured annotated tag {tag} targets {head}")


def bootstrap_baseline(root: Path, policy: ReleasePolicy, context: CiContext, confirmation: str) -> None:
    paths = ReleasePaths(root, policy)
    validate_root(paths)
    require_ci(root, context, "workflow_dispatch")
    if confirmation != policy.baseline_confirmation:
        raise ReleaseError(f"Baseline confirmation must be exactly: {policy.baseline_confirmation}")
    target = git(root, "rev-parse", f"{policy.baseline_commit}^{{commit}}")
    source = git(root, "show", f"{target}:{policy.files[0]}")
    if project_version(source) != policy.baseline_version:
        raise ReleaseError(f"Historical commit {target} did not introduce ocint {policy.baseline_version}")
    target_with_parents = git(root, "rev-list", "--parents", "-n", "1", target).split()
    if len(target_with_parents) > 2:
        raise ReleaseError(f"Historical commit {target} must not be a merge commit")
    if len(target_with_parents) == 2 and git_path_exists(root, target_with_parents[1], policy.files[0]):
        raise ReleaseError(f"Historical commit {target} did not introduce {policy.files[0]}")
    tag = policy.tag(policy.baseline_version)
    if ensure_tag(root, tag, target):
        create_ci_tag(root, tag, target, f"ocint v{policy.baseline_version}")
    run(["git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}"], cwd=root, capture=False)
    print(f"Ensured historical baseline tag {tag} targets {target}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Prepare and validate PR-only ocint releases")
    result.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3], help=argparse.SUPPRESS)
    commands = result.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("version")
    validate_parser = commands.add_parser("validate-pr")
    validate_parser.add_argument("--base", required=True)
    validate_parser.add_argument("--base-ref", required=True)
    validate_parser.add_argument("--title", required=True)
    validate_parser.add_argument("--branch", default=os.environ.get("GITHUB_HEAD_REF", ""))
    commands.add_parser("ci-tag")
    baseline_parser = commands.add_parser("bootstrap-baseline")
    baseline_parser.add_argument("--confirmation", required=True)
    return result


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    policy = release_policy()
    root = args.root.resolve()
    try:
        match args.command:
            case "prepare":
                prepare(root, SemVer.parse(args.version), policy)
            case "validate-pr":
                validate_pr(root, args.base, args.base_ref, args.title, args.branch, policy)
            case "ci-tag":
                ci_tag(root, policy, ci_context())
            case "bootstrap-baseline":
                bootstrap_baseline(root, policy, ci_context(), args.confirmation)
    except ReleaseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
