from datetime import date
from pathlib import Path

import pytest
from scripts.ocint_release import (
    ReleaseError,
    SemVer,
    changelog_section,
    parse_ocint_commit,
    parse_porcelain_status,
    parse_pr_title,
    parse_release_title,
    prepared_release_date,
    project_version,
    release_candidate,
    release_policy,
    updated_changelog,
)


@pytest.mark.parametrize("value", ["0.1.0", "1.2.3", "10.20.30"])
def test_stable_semver_round_trips(value: str) -> None:
    # GIVEN a strict stable version
    # WHEN it is parsed
    parsed = SemVer.parse(value)

    # THEN formatting preserves it
    assert str(parsed) == value


@pytest.mark.parametrize("value", ["1", "1.2", "v1.2.3", "01.2.3", "1.2.3-rc.1", "1.2.3+meta"])
def test_non_stable_semver_is_rejected(value: str) -> None:
    # GIVEN a non-stable or non-canonical version
    # WHEN/THEN it is parsed
    with pytest.raises(ReleaseError, match="stable SemVer"):
        SemVer.parse(value)


def test_semver_orders_numerically() -> None:
    # GIVEN numeric semantic versions
    # WHEN they are compared
    # THEN component ordering is used
    assert SemVer.parse("0.10.0") > SemVer.parse("0.9.9")


def test_project_version_reads_authoritative_project_field() -> None:
    # GIVEN package metadata
    source = '[project]\nname = "ocint"\nversion = "2.3.4"\n'

    # WHEN the version is read
    result = project_version(source)

    # THEN it is a validated SemVer
    assert result == SemVer(2, 3, 4)


@pytest.mark.parametrize(
    "title",
    ["ocint: Release v1.2.3", "ocint: Release v1.2.3 (#42)"],
)
def test_release_title_accepts_pr_suffix_only_for_merged_subject(title: str) -> None:
    # GIVEN a canonical release subject with an optional GitHub suffix
    # WHEN the title is parsed
    result = parse_release_title(title)

    # THEN its version is returned
    assert result == SemVer(1, 2, 3)


@pytest.mark.parametrize(
    "title",
    ["ocint: release v1.2.3", "ocint: Release 1.2.3", "ocint: Release v1.2.3 (#0)", "ocint: Release v1.2.3 extra"],
)
def test_malformed_release_title_is_rejected(title: str) -> None:
    # GIVEN a noncanonical release subject
    # WHEN/THEN it is parsed
    with pytest.raises(ReleaseError, match="Expected release title"):
        parse_release_title(title)


def test_release_policy_names_branch_title_tag_and_exact_files() -> None:
    # GIVEN the repository release policy
    policy = release_policy()
    version = SemVer(1, 2, 3)

    # WHEN release identities are rendered
    result = (policy.branch(version), policy.title(version), policy.tag(version), policy.files)

    # THEN all names and the exact file allowlist are canonical
    assert result == (
        "ocint-release/v1.2.3",
        "ocint: Release v1.2.3",
        "ocint-v1.2.3",
        ("bin/ocint/pyproject.toml", "bin/ocint/CHANGELOG.md", "uv.lock"),
    )


@pytest.mark.parametrize(
    ("branch", "title", "files", "base_version", "head_version"),
    [
        ("ocint-release/bad", "chore: ordinary", set(), SemVer(0, 1, 0), SemVer(0, 1, 0)),
        ("chore/ordinary", "ocint: release malformed", set(), SemVer(0, 1, 0), SemVer(0, 1, 0)),
        ("chore/ordinary", "chore: ordinary", {"bin/ocint/CHANGELOG.md"}, SemVer(0, 1, 0), SemVer(0, 1, 0)),
        ("chore/ordinary", "chore: ordinary", set(), SemVer(0, 1, 0), SemVer(0, 2, 0)),
    ],
)
def test_strong_release_signals_make_pr_candidate(
    branch: str,
    title: str,
    files: set[str],
    base_version: SemVer,
    head_version: SemVer,
) -> None:
    # GIVEN one strong release signal
    # WHEN applicability is evaluated
    result = release_candidate(
        release_policy(),
        branch=branch,
        title=title,
        files=files,
        base_version=base_version,
        head_version=head_version,
    )

    # THEN release policy applies
    assert result is True


@pytest.mark.parametrize("files", [{"uv.lock"}, {"bin/ocint/pyproject.toml"}])
def test_weak_shared_file_change_is_not_release_candidate(files: set[str]) -> None:
    # GIVEN an ordinary branch and title with an unchanged package version
    # WHEN applicability is evaluated for a weak shared-file signal
    result = release_candidate(
        release_policy(),
        branch="chore/dependencies",
        title="chore: Update dependencies",
        files=files,
        base_version=SemVer(0, 1, 0),
        head_version=SemVer(0, 1, 0),
    )

    # THEN release validation is not applicable
    assert result is False


def test_pr_title_does_not_accept_merge_suffix() -> None:
    # GIVEN a merge commit subject rather than an exact PR title
    # WHEN/THEN PR title parsing runs
    with pytest.raises(ReleaseError, match="Expected release title"):
        parse_pr_title("ocint: Release v1.2.3 (#42)")


def test_tag_workflow_extracts_tagger_from_trusted_parent() -> None:
    # GIVEN the repository release workflow
    workflow = (Path(__file__).resolve().parents[5] / ".github/workflows/ocint-release.yml").read_text()

    # WHEN the write-token tag step is inspected
    tag_step = workflow.split("tag-merged-release:", 1)[1]

    # THEN it extracts and executes the parent revision's validator
    assert 'git show "$parent:bin/ocint/scripts/ocint_release.py"' in tag_step
    assert 'python "$validator" --root "$GITHUB_WORKSPACE" ci-tag' in tag_step
    assert "python bin/ocint/scripts/ocint_release.py ci-tag" not in tag_step
    assert "workflow_dispatch" not in workflow
    assert "bootstrap-baseline" not in workflow


def test_valid_ocint_commit_preserves_pr_suffix() -> None:
    # GIVEN a conventionally scoped commit
    # WHEN it is parsed
    result = parse_ocint_commit("ocint: Improve release safety (#42)")

    # THEN only the scope is removed
    assert result == "Improve release safety (#42)"


def test_unrelated_commit_is_filtered() -> None:
    # GIVEN another scope
    # WHEN it is parsed
    result = parse_ocint_commit("nvim: Update plugin")

    # THEN it is omitted
    assert result is None


@pytest.mark.parametrize("subject", ["ocint:Add feature", "ocint: ", "Ocint: feature", "ocint feature"])
def test_malformed_ocint_prefix_is_rejected(subject: str) -> None:
    # GIVEN an almost-ocint prefix
    # WHEN/THEN it is parsed
    with pytest.raises(ReleaseError, match="Malformed"):
        parse_ocint_commit(subject)


def test_changelog_uses_release_date_and_subjects_only() -> None:
    # GIVEN Git-log subjects in newest-first order and a deterministic UTC date
    commits = ["Newer (#7)", "Older"]

    # WHEN a section is rendered
    section = changelog_section(SemVer(0, 2, 0), commits, date(2026, 7, 11))

    # THEN the heading has one date and bullets contain no commit metadata
    assert section == "## 0.2.0 - 2026-07-11\n\n- Newer (#7)\n- Older\n"


def test_changelog_prepends_without_rewriting_history() -> None:
    # GIVEN an existing changelog
    existing = "# Changelog\n\n## 0.1.0 - 2026-07-01\n\n- baseline\n"

    # WHEN the next release is generated
    result = updated_changelog(existing, SemVer(0, 2, 0), ["Feature (#9)"], date(2026, 7, 11))

    # THEN the prior section remains after the new section
    assert result == ("# Changelog\n\n## 0.2.0 - 2026-07-11\n\n- Feature (#9)\n\n## 0.1.0 - 2026-07-01\n\n- baseline\n")


def test_prepared_release_date_is_reused_during_later_validation() -> None:
    # GIVEN a changelog prepared on an earlier UTC date
    changelog = "# Changelog\n\n## 0.2.0 - 2026-07-11\n\n- Feature (#9)\n"

    # WHEN its release date is read for PR validation
    result = prepared_release_date(changelog, SemVer(0, 2, 0))

    # THEN the prepared date is retained
    assert result == date(2026, 7, 11)


@pytest.mark.parametrize("value", ["2026-99-11", "11-07-2026", ""])
def test_invalid_prepared_release_date_is_rejected(value: str) -> None:
    # GIVEN a malformed prepared heading
    changelog = f"# Changelog\n\n## 0.2.0 - {value}\n\n- Feature\n"

    # WHEN/THEN release date validation runs
    with pytest.raises(ReleaseError, match=r"release (date|heading)"):
        prepared_release_date(changelog, SemVer(0, 2, 0))


def test_porcelain_parser_preserves_unusual_paths() -> None:
    # GIVEN NUL-delimited status containing spaces, quotes, and a newline
    raw = b' M ordinary path\0?? quoted"path\0?? line\nbreak\0'

    # WHEN status is parsed
    result = parse_porcelain_status(raw)

    # THEN paths are returned literally rather than Git-quoted or line-split
    assert result == {"ordinary path", 'quoted"path', "line\nbreak"}


@pytest.mark.parametrize("status", [b"R  renamed\0old\0", b" C copied\0source\0"])
def test_porcelain_parser_rejects_rename_and_copy_states(status: bytes) -> None:
    # GIVEN a rename-like status with a second NUL-delimited path
    # WHEN/THEN status is parsed
    with pytest.raises(ReleaseError, match="Renamed or copied"):
        parse_porcelain_status(status)
