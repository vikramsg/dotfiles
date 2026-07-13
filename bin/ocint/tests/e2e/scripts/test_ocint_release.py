import re
import subprocess

from tests.support.release_workspace import ReleaseWorkspace


def test_pr_release_is_prepared_validated_and_tagged_only_after_squash_merge(
    release_workspace: ReleaseWorkspace,
) -> None:
    # GIVEN a release branch at origin/main in a disposable repository
    root = release_workspace.root
    initial_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    remote_before_prepare = subprocess.run(
        ["git", "--git-dir", str(release_workspace.remote), "for-each-ref", "--format=%(refname) %(objectname)"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout

    # WHEN preparation runs twice
    command = ["python", "bin/ocint/scripts/ocint_release.py", "prepare", "0.2.0"]
    first = subprocess.run(command, cwd=root, env=release_workspace.environment, text=True, capture_output=True)
    second = subprocess.run(command, cwd=root, env=release_workspace.environment, text=True, capture_output=True)

    # THEN exactly three files change without local or remote history mutation
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "already prepared" in second.stdout
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.split(b"\0")
    assert {entry[3:].decode() for entry in status if entry} == {
        "bin/ocint/CHANGELOG.md",
        "bin/ocint/pyproject.toml",
        "uv.lock",
    }
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == initial_head
    )
    assert re.fullmatch(
        r"# Changelog\n\n## 0\.2\.0 - \d{4}-\d{2}-\d{2}\n\n- Add safe release flow \(#12\)\n",
        (root / "bin/ocint/CHANGELOG.md").read_text(),
    )
    assert (
        subprocess.run(
            ["git", "--git-dir", str(release_workspace.remote), "for-each-ref", "--format=%(refname) %(objectname)"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        == remote_before_prepare
    )

    # WHEN the release files are committed as a PR head and read-only validation runs
    subprocess.run(
        ["git", "add", "--", "bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"], cwd=root, check=True
    )
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0"], cwd=root, check=True, capture_output=True)
    validated = subprocess.run(
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

    # THEN validation succeeds without mutation
    assert validated.returncode == 0, validated.stderr
    release_branch_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    assert (
        subprocess.run(
            ["git", "tag", "--list", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout
        == ""
    )

    # WHEN GitHub's squash merge is simulated and the guarded CI operation runs
    subprocess.run(["git", "switch", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "reset", "--hard", release_workspace.baseline_remote_head], cwd=root, check=True, capture_output=True
    )
    subprocess.run(["git", "merge", "--squash", release_branch_head], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "ocint: Release v0.2.0 (#99)"], cwd=root, check=True, capture_output=True)
    merged_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    subprocess.run(["git", "push", "origin", "main"], cwd=root, check=True, capture_output=True)
    remote_main_before_tag = subprocess.run(
        ["git", "--git-dir", str(release_workspace.remote), "rev-parse", "refs/heads/main"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    environment = {
        **release_workspace.environment,
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": merged_head,
    }
    tagged = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )
    retried = subprocess.run(
        ["python", "bin/ocint/scripts/ocint_release.py", "ci-tag"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
    )

    # THEN CI idempotently creates and pushes only an annotated tag on the merged commit
    assert tagged.returncode == 0, tagged.stderr
    assert retried.returncode == 0, retried.stderr
    assert (
        subprocess.run(
            ["git", "cat-file", "-t", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == "tag"
    )
    assert (
        subprocess.run(
            ["git", "rev-list", "-n", "1", "ocint-v0.2.0"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        == merged_head
    )
    assert (
        subprocess.run(
            ["git", "--git-dir", str(release_workspace.remote), "rev-list", "-n", "1", "ocint-v0.2.0"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == merged_head
    )
    assert (
        subprocess.run(
            ["git", "--git-dir", str(release_workspace.remote), "rev-parse", "refs/heads/main"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        == remote_main_before_tag
    )
    assert not (root.parent / "tool-bin" / "ocint").exists()
