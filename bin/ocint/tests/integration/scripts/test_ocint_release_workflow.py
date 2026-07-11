import subprocess

from tests.support.release_workspace import ReleaseWorkspace


def test_prepare_is_idempotent_and_rejects_unrelated_publish_changes(release_workspace: ReleaseWorkspace) -> None:
    # GIVEN a clean main equal to a real origin/main with annotated history
    command = ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"]

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
