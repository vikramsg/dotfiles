import re
import subprocess

from tests.support.release_workspace import ReleaseWorkspace


def test_real_prepare_publish_install_and_recovery_leave_remote_unchanged(
    release_workspace: ReleaseWorkspace,
) -> None:
    # GIVEN a disposable installable ocint workspace, bare origin, and isolated uv tool directories
    root = release_workspace.root
    environment = release_workspace.environment
    before_prepare_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # WHEN a real prepare and confirmed publish run
    prepared = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )
    pre_publish_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()

    # THEN prepare immediately leaves exactly three paths and no commit or target tag
    assert prepared.returncode == 0, prepared.stderr
    prepared_paths = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.split(b"\0")
    assert {entry[3:].decode() for entry in prepared_paths if entry} == {
        "bin/ocint/CHANGELOG.md",
        "bin/ocint/pyproject.toml",
        "uv.lock",
    }
    assert pre_publish_head == before_prepare_head == release_workspace.baseline_remote_head
    assert (
        subprocess.run(
            ["git", "tag", "--list", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout
        == ""
    )
    changelog = (root / "bin" / "ocint" / "CHANGELOG.md").read_text()
    assert re.fullmatch(
        r"# Changelog\n\n## 0\.2\.0 - \d{4}-\d{2}-\d{2}\n\n- Add safe release flow \(#12\)\n",
        changelog,
    )
    published = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "publish", "0.2.0", "--yes"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN preparation did not commit, publishing made the exact commit and annotated tag, and installation is isolated
    assert published.returncode == 0, published.stderr
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    assert subject == "ocint: Release v0.2.0"
    assert (
        subprocess.run(
            ["git", "cat-file", "-t", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == "tag"
    )
    tag_target = subprocess.run(
        ["git", "rev-list", "-n", "1", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    assert (
        tag_target
        == subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
    )
    installed = subprocess.run(
        [str(root.parent / "tool-bin" / "ocint"), "--version"],
        cwd=root,
        env=environment,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert installed == "ocint 0.2.0\n"
    remote_refs = subprocess.run(
        [
            "git",
            "--git-dir",
            str(release_workspace.remote),
            "for-each-ref",
            "--format=%(refname) %(objectname)",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert remote_refs == release_workspace.baseline_remote_refs

    # WHEN publish is retried after both commit and tag already exist
    retried = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "publish", "0.2.0", "--yes"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN recovery is idempotent and creates no additional commit
    assert retried.returncode == 0, retried.stderr
    assert (
        subprocess.run(
            ["git", "rev-list", "--count", f"{pre_publish_head}..HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == "1"
    )
