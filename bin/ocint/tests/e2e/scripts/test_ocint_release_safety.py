import subprocess

from tests.support.release_workspace import ReleaseWorkspace


def test_prepare_is_idempotent_and_rejects_unrelated_publish_changes(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a clean main equal to a real origin/main with annotated history
    command = ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"]
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=release_workspace.root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN preparation and an idempotent retry run
    first = subprocess.run(
        command, cwd=release_workspace.root, env=release_workspace.environment, text=True, capture_output=True
    )
    second = subprocess.run(
        command, cwd=release_workspace.root, env=release_workspace.environment, text=True, capture_output=True
    )

    # THEN only the three release files changed and no commit or tag was created
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=release_workspace.root, check=True, text=True, capture_output=True
    ).stdout
    assert {line[3:] for line in status.splitlines()} == {
        "bin/ocint/CHANGELOG.md",
        "bin/ocint/pyproject.toml",
        "uv.lock",
    }
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=release_workspace.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == initial_head
    )
    assert "already prepared" in second.stdout
    tags = subprocess.run(
        ["git", "tag", "--list", "ocint-v0.2.0"],
        cwd=release_workspace.root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert tags == ""
    (release_workspace.root / "unrelated.txt").write_text("user work\n")

    rejected = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "publish", "0.2.0", "--yes"],
        cwd=release_workspace.root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    assert rejected.returncode == 1
    assert "exactly the three" in rejected.stderr


def test_publish_recovers_when_release_commit_exists_without_tag(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a prepared release manually committed before tag creation
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
        ["git", "add", "--", "bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0"], cwd=root, check=True, capture_output=True)
    release_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN publish resumes
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "publish", "0.2.0", "--yes"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it tags the existing commit without creating another commit
    assert result.returncode == 0, result.stderr
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == release_commit
    )
    assert (
        subprocess.run(
            ["git", "rev-list", "-n", "1", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == release_commit
    )


def test_publish_recovers_after_commit_and_tag_before_install(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a release commit and annotated tag but no installed fixture tool
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
        ["git", "add", "--", "bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "tag", "-a", "ocint-v0.2.0", "-m", "ocint v0.2.0"], cwd=root, check=True)
    release_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    executable = root.parent / "tool-bin" / "ocint"
    assert not executable.exists()

    # WHEN publish resumes after the equivalent of a failed install
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "publish", "0.2.0", "--yes"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it verifies installation without duplicating commit or tag
    assert result.returncode == 0, result.stderr
    assert executable.exists()
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == release_commit
    )
    assert (
        subprocess.run(
            ["git", "rev-list", "--count", f"{release_workspace.baseline_remote_head}..HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == "1"
    )


def test_prepare_restores_files_when_verification_fails(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a clean release repo whose package check fails
    justfile = release_workspace.root / "bin" / "ocint" / "justfile"
    justfile.write_text("test:\n    @true\ncheck:\n    @false\nsmoke:\n    @true\n")
    subprocess.run(["git", "add", str(justfile)], cwd=release_workspace.root, check=True)
    subprocess.run(["git", "commit", "-m", "ocint: Exercise rollback"], cwd=release_workspace.root, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=release_workspace.root, check=True, capture_output=True)
    before_project = (release_workspace.root / "bin" / "ocint" / "pyproject.toml").read_bytes()
    before_lock = (release_workspace.root / "uv.lock").read_bytes()

    # WHEN preparation reaches the failing real recipe
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=release_workspace.root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN every mutated file is restored
    assert result.returncode == 1
    assert (release_workspace.root / "bin" / "ocint" / "pyproject.toml").read_bytes() == before_project
    assert (release_workspace.root / "uv.lock").read_bytes() == before_lock
    assert not (release_workspace.root / "bin" / "ocint" / "CHANGELOG.md").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=release_workspace.root, check=True, text=True, capture_output=True
    ).stdout
    assert status == ""


def test_prepare_rejects_lightweight_release_tag_without_mutation(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN the baseline version is marked by a lightweight tag
    root = release_workspace.root
    target = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "--delete", "ocint-v0.1.0"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "tag", "ocint-v0.1.0", target], cwd=root, check=True)
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN preparation validates release history
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it rejects the tag before changing release files or history
    assert result.returncode == 1
    assert "must be annotated" in result.stderr
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == initial_head
    )
    assert not (root / "bin" / "ocint" / "CHANGELOG.md").exists()


def test_prepare_rejects_tag_version_content_mismatch(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN the newest release tag claims a version absent from its commit
    root = release_workspace.root
    target = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "tag", "-a", "ocint-v0.1.1", target, "-m", "ocint v0.1.1"], cwd=root, check=True)

    # WHEN preparation validates the tagged package metadata
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it fails without changing files or commits
    assert result.returncode == 1
    assert "does not contain package version" in result.stderr
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )
    assert not (root / "bin" / "ocint" / "CHANGELOG.md").exists()


def test_prepare_rejects_main_diverged_from_known_origin(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN local main has advanced beyond locally known origin/main
    root = release_workspace.root
    (root / "local-only.txt").write_text("local commit\n")
    subprocess.run(["git", "add", "local-only.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "chore: local only"], cwd=root, check=True, capture_output=True)
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN preparation checks the branch boundary
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it fails before release mutation
    assert result.returncode == 1
    assert "must exactly equal" in result.stderr
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == initial_head
    )
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )
    assert not (root / "bin" / "ocint" / "CHANGELOG.md").exists()


def test_prepare_rejects_non_increasing_version_without_mutation(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN the requested version equals the current tagged package version
    root = release_workspace.root
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN preparation is requested
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.1.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN version progression fails before release mutation
    assert result.returncode == 1
    assert "must be greater" in result.stderr
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == initial_head
    )
    assert (
        subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, text=True, capture_output=True).stdout
        == ""
    )
    assert not (root / "bin" / "ocint" / "CHANGELOG.md").exists()


def test_publish_rejects_conflicting_target_tag_without_commit_or_install(
    release_workspace: ReleaseWorkspace,
) -> None:
    # GIVEN a prepared release and a conflicting target-version tag on the baseline commit
    root = release_workspace.root
    prepared = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )
    assert prepared.returncode == 0, prepared.stderr
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    baseline = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.1.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(
        ["git", "tag", "-a", "ocint-v0.2.0", baseline, "-m", "conflicting ocint v0.2.0"], cwd=root, check=True
    )

    # WHEN publish validates release history
    result = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "publish", "0.2.0", "--yes"],
        cwd=root,
        env=release_workspace.environment,
        text=True,
        capture_output=True,
    )

    # THEN it rejects the conflict without committing, installing, or changing remote refs
    assert result.returncode == 1
    assert "conflicts with release tag history" in result.stderr
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == initial_head
    )
    assert not (root.parent / "tool-bin" / "ocint").exists()
    remote_refs = subprocess.run(
        ["git", "--git-dir", str(release_workspace.remote), "for-each-ref", "--format=%(refname) %(objectname)"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert remote_refs == release_workspace.baseline_remote_refs
