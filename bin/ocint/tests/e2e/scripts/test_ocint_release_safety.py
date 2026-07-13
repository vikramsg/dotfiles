import subprocess

import pytest
from scripts.ocint_release import CiContext, ReleaseError, ReleasePolicy, SemVer, bootstrap_baseline
from tests.support.release_workspace import ReleaseWorkspace


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ("wrong-branch", "Prepare must run on branch"),
        ("diverged", "must exactly equal"),
        ("lightweight-tag", "must be annotated"),
        ("mismatched-tag", "does not contain package version"),
        ("non-increasing", "must be greater"),
    ],
)
def test_prepare_failures_do_not_mutate_release_files(
    release_workspace: ReleaseWorkspace, setup: str, message: str
) -> None:
    # GIVEN an invalid preparation state
    root = release_workspace.root
    version = "0.1.0" if setup == "non-increasing" else "0.2.0"
    if setup == "wrong-branch":
        subprocess.run(["git", "switch", "main"], cwd=root, check=True, capture_output=True)
    elif setup == "diverged":
        (root / "local-only.txt").write_text("local\n")
        subprocess.run(["git", "add", "local-only.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "chore: local"], cwd=root, check=True, capture_output=True)
    elif setup == "lightweight-tag":
        target = subprocess.run(
            ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        subprocess.run(["git", "tag", "-d", "ocint-v0.1.0"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "tag", "ocint-v0.1.0", target], cwd=root, check=True)
    elif setup == "mismatched-tag":
        target = subprocess.run(
            ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        subprocess.run(["git", "tag", "-a", "ocint-v0.1.1", target, "-m", "mismatch"], cwd=root, check=True)
    elif setup == "non-increasing":
        subprocess.run(
            ["git", "switch", "-c", "ocint-release/v0.1.0", "origin/main"],
            cwd=root,
            check=True,
            capture_output=True,
        )
    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True
    ).stdout

    # WHEN preparation is attempted
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", version],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it fails without release-file mutation
    assert result.returncode == 1
    assert message in result.stderr
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == before
    )
    assert not (root / "bin/ocint/CHANGELOG.md").exists()


def test_prepare_rolls_back_when_checks_fail(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a release base whose check recipe fails
    root = release_workspace.root
    subprocess.run(["git", "switch", "main"], cwd=root, check=True, capture_output=True)
    justfile = root / "bin/ocint/justfile"
    justfile.write_text("test:\n    @true\ncheck:\n    @false\nsmoke:\n    @true\n")
    subprocess.run(["git", "add", "bin/ocint/justfile"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "ocint: Exercise rollback"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "switch", "-C", "ocint-release/v0.2.0", "origin/main"], cwd=root, check=True, capture_output=True
    )
    before_project = (root / "bin/ocint/pyproject.toml").read_bytes()
    before_lock = (root / "uv.lock").read_bytes()

    # WHEN preparation reaches the failing check
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN all three release paths are restored
    assert result.returncode == 1
    assert (root / "bin/ocint/pyproject.toml").read_bytes() == before_project
    assert (root / "uv.lock").read_bytes() == before_lock
    assert not (root / "bin/ocint/CHANGELOG.md").exists()
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )


@pytest.mark.parametrize(
    ("title", "branch", "message"),
    [
        ("ocint: release v0.2.0", "ocint-release/v0.2.0", "title must be exactly"),
        ("ocint: Release v0.2.0", "release/0.2.0", "branch must be exactly"),
    ],
)
def test_validate_pr_rejects_malformed_identity(
    release_workspace: ReleaseWorkspace, title: str, branch: str, message: str
) -> None:
    # GIVEN a prepared and committed release PR
    root = release_workspace.root
    prepared = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )
    assert prepared.returncode == 0, prepared.stderr
    subprocess.run(
        ["git", "add", "--", "bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"], cwd=root, check=True
    )
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0"], cwd=root, check=True, capture_output=True)

    # WHEN PR validation receives malformed identity data
    result = subprocess.run(
        [
            "python",
            "bin/ocint/scripts/ocint_release.py",
            "validate-pr",
            "--base",
            release_workspace.baseline_remote_head,
            "--base-ref",
            "main",
            "--title",
            title,
            "--branch",
            branch,
        ],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN validation fails without mutation
    assert result.returncode == 1
    assert message in result.stderr
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )


@pytest.mark.parametrize("change", ["partial", "unexpected"])
def test_validate_pr_rejects_non_exact_release_files(release_workspace: ReleaseWorkspace, change: str) -> None:
    # GIVEN a clean PR head with a partial or unexpected file set
    root = release_workspace.root
    if change == "partial":
        pyproject = root / "bin/ocint/pyproject.toml"
        pyproject.write_text(pyproject.read_text().replace('version = "0.1.0"', 'version = "0.2.0"'))
        subprocess.run(["git", "add", "bin/ocint/pyproject.toml"], cwd=root, check=True)
    else:
        (root / "unexpected.txt").write_text("unexpected\n")
        subprocess.run(["git", "add", "unexpected.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "chore: invalid release files"], cwd=root, check=True, capture_output=True)

    # WHEN release PR validation runs
    result = subprocess.run(
        [
            "python",
            "bin/ocint/scripts/ocint_release.py",
            "validate-pr",
            "--base",
            release_workspace.baseline_remote_head,
            "--base-ref",
            "main",
            "--title",
            "ocint: Release v0.2.0",
            "--branch",
            "ocint-release/v0.2.0",
        ],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN exact-file policy rejects it without further mutation
    assert result.returncode == 1
    assert "exactly the three release files" in result.stderr
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )


def test_ci_tag_rejects_conflicting_target_tag(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a valid simulated squash merge and target tag already on its parent
    root = release_workspace.root
    prepared = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )
    assert prepared.returncode == 0, prepared.stderr
    subprocess.run(
        ["git", "add", "--", "bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"], cwd=root, check=True
    )
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0"], cwd=root, check=True, capture_output=True)
    release_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "switch", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "reset", "--hard", release_workspace.baseline_remote_head], cwd=root, check=True, capture_output=True
    )
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "merge", "--squash", release_head], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0 (#7)"], cwd=root, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "-a", "ocint-v0.2.0", parent, "-m", "conflict"], cwd=root, check=True)
    environment = {
        **release_workspace.environment,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": head,
    }

    # WHEN guarded tag creation validates the target tag
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN the conflict fails without changing the tag or remote
    assert result.returncode == 1
    assert "Conflicting tag exists" in result.stderr
    assert (
        subprocess.run(
            ["git", "rev-list", "-n", "1", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == parent
    )
    assert (
        subprocess.run(
            ["git", "--git-dir", str(release_workspace.remote), "tag", "--list", "ocint-v0.2.0"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        == ""
    )


def test_ci_tag_rejects_missing_ci_guards(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a local release workspace without GitHub Actions identity
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=release_workspace.root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN the CI-only tag operation is invoked locally
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=release_workspace.root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it refuses before changing history or the remote
    assert result.returncode == 1
    assert "restricted to GitHub Actions" in result.stderr
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=release_workspace.root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == head
    )
    assert (
        subprocess.run(
            ["git", "tag", "--list", "ocint-v0.2.0"],
            cwd=release_workspace.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        == ""
    )


@pytest.mark.parametrize("change", ["lock", "pyproject-config"])
def test_validate_pr_treats_weak_ordinary_changes_as_not_applicable(
    release_workspace: ReleaseWorkspace, change: str
) -> None:
    # GIVEN an ordinary PR that changes a weak shared file without changing the ocint version
    root = release_workspace.root
    subprocess.run(["git", "switch", "-c", "chore/ordinary", "origin/main"], cwd=root, check=True, capture_output=True)
    if change == "lock":
        lock = root / "uv.lock"
        lock.write_text(f"{lock.read_text()}\n")
        subprocess.run(["git", "add", "uv.lock"], cwd=root, check=True)
    else:
        pyproject = root / "bin/ocint/pyproject.toml"
        pyproject.write_text(f'{pyproject.read_text()}\n[tool.fixture]\nvalue = "ordinary"\n')
        subprocess.run(["git", "add", "bin/ocint/pyproject.toml"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "chore: ordinary metadata"], cwd=root, check=True, capture_output=True)

    # WHEN release PR validation runs
    result = subprocess.run(
        [
            "python",
            "bin/ocint/scripts/ocint_release.py",
            "validate-pr",
            "--base",
            release_workspace.baseline_remote_head,
            "--base-ref",
            "main",
            "--title",
            "chore: Ordinary metadata",
            "--branch",
            "chore/ordinary",
        ],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it succeeds read-only as not applicable
    assert result.returncode == 0, result.stderr
    assert "not applicable" in result.stdout
    assert subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True
    ).stdout == ""


def test_validate_pr_rejects_non_main_base_ref(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN an ordinary clean PR checkout
    root = release_workspace.root

    # WHEN validation is pointed at a non-main base ref
    result = subprocess.run(
        [
            "python",
            "bin/ocint/scripts/ocint_release.py",
            "validate-pr",
            "--base",
            release_workspace.baseline_remote_head,
            "--base-ref",
            "develop",
            "--title",
            "chore: Ordinary",
            "--branch",
            "chore/ordinary",
        ],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN base policy fails even though release validation would be inapplicable
    assert result.returncode == 1
    assert "base ref main" in result.stderr


def test_ci_tag_rejects_ordinary_subject_without_mutation(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN valid push-event guards on an ordinary ocint commit
    root = release_workspace.root
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    environment = {
        **release_workspace.environment,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": head,
    }

    # WHEN the command-level tagger is called
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN it rejects the subject and creates no tag
    assert result.returncode == 1
    assert "Expected release title" in result.stderr
    assert subprocess.run(
        ["git", "tag", "--list", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout == ""


def test_ci_tag_rejects_malformed_release_subject(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a malformed release-like commit under otherwise valid push guards
    root = release_workspace.root
    subprocess.run(["git", "commit", "--allow-empty", "-m", "ocint: release v0.2"], cwd=root, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    environment = {
        **release_workspace.environment,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": head,
    }

    # WHEN command-level subject validation runs
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN malformed release syntax fails without a target tag
    assert result.returncode == 1
    assert "Expected release title" in result.stderr
    assert subprocess.run(
        ["git", "tag", "--list", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout == ""


@pytest.mark.parametrize("guard", ["event", "ref", "sha"])
def test_ci_tag_rejects_incorrect_github_push_identity(release_workspace: ReleaseWorkspace, guard: str) -> None:
    # GIVEN one incorrect GitHub push identity field
    root = release_workspace.root
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    environment = {
        **release_workspace.environment,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request" if guard == "event" else "push",
        "GITHUB_REF": "refs/heads/other" if guard == "ref" else "refs/heads/main",
        "GITHUB_SHA": "0" * 40 if guard == "sha" else head,
    }

    # WHEN CI tag creation checks its boundary
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN it fails before tag mutation
    assert result.returncode == 1
    assert "GitHub Actions" in result.stderr or "GITHUB_SHA" in result.stderr
    assert subprocess.run(
        ["git", "tag", "--list", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout == ""


@pytest.mark.parametrize("invalid", ["event", "confirmation"])
def test_baseline_rejects_wrong_command_boundary(
    release_workspace: ReleaseWorkspace, invalid: str
) -> None:
    # GIVEN typed baseline policy and one invalid workflow-dispatch boundary value
    root = release_workspace.root
    target = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    policy = ReleasePolicy(
        files=("bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"),
        baseline_version=SemVer(0, 1, 0),
        baseline_commit=target,
        baseline_confirmation="confirm fixture baseline",
    )
    context = CiContext(
        actions="true",
        event_name="push" if invalid == "event" else "workflow_dispatch",
        ref="refs/heads/main",
        sha=head,
    )
    confirmation = "wrong" if invalid == "confirmation" else policy.baseline_confirmation

    # WHEN baseline creation is requested
    with pytest.raises(ReleaseError, match="GitHub Actions|confirmation"):
        bootstrap_baseline(root, policy, context, confirmation)

    # THEN the existing fixture baseline remains unchanged
    assert subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip() == target


def test_baseline_creates_and_idempotently_pushes_fixture_introduction_tag(
    release_workspace: ReleaseWorkspace,
) -> None:
    # GIVEN typed policy targeting the fixture's actual package-introduction commit and no baseline tag
    root = release_workspace.root
    target = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "-d", "ocint-v0.1.0"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "--git-dir", str(release_workspace.remote), "update-ref", "-d", "refs/tags/ocint-v0.1.0"],
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    policy = ReleasePolicy(
        files=("bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"),
        baseline_version=SemVer(0, 1, 0),
        baseline_commit=target,
        baseline_confirmation="confirm fixture baseline",
    )
    context = CiContext(actions="true", event_name="workflow_dispatch", ref="refs/heads/main", sha=head)

    # WHEN baseline creation and a same-target retry run against the disposable bare origin
    bootstrap_baseline(root, policy, context, policy.baseline_confirmation)
    bootstrap_baseline(root, policy, context, policy.baseline_confirmation)

    # THEN both local and remote annotated tags target the introduction commit
    assert subprocess.run(
        ["git", "cat-file", "-t", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip() == "tag"
    assert subprocess.run(
        ["git", "--git-dir", str(release_workspace.remote), "rev-list", "-n", "1", "ocint-v0.1.0"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip() == target


def test_baseline_rejects_conflicting_fixture_tag(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN typed introduction policy and a same-name tag targeting another commit
    root = release_workspace.root
    target = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "-d", "ocint-v0.1.0"], cwd=root, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "-a", "ocint-v0.1.0", head, "-m", "conflict"], cwd=root, check=True)
    policy = ReleasePolicy(
        files=("bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"),
        baseline_version=SemVer(0, 1, 0),
        baseline_commit=target,
        baseline_confirmation="confirm fixture baseline",
    )
    context = CiContext(actions="true", event_name="workflow_dispatch", ref="refs/heads/main", sha=head)

    # WHEN baseline creation validates tag state
    with pytest.raises(ReleaseError, match="Conflicting tag"):
        bootstrap_baseline(root, policy, context, policy.baseline_confirmation)

    # THEN the conflict remains local and the disposable remote baseline remains correct
    assert subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip() == head
    assert subprocess.run(
        ["git", "--git-dir", str(release_workspace.remote), "rev-list", "-n", "1", "ocint-v0.1.0"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip() == target
