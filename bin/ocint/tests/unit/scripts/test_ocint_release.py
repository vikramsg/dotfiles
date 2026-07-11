from datetime import UTC, datetime

import pytest

from scripts.ocint_release import (
    Commit,
    ReleaseError,
    SemVer,
    changelog_section,
    parse_ocint_commit,
    project_version,
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


def test_valid_ocint_commit_preserves_pr_suffix() -> None:
    # GIVEN a conventionally scoped commit
    # WHEN it is parsed
    result = parse_ocint_commit("a" * 40, 123, "ocint: Improve release safety (#42)")

    # THEN only the scope is removed
    assert result == Commit("a" * 40, 123, "Improve release safety (#42)")


def test_unrelated_commit_is_filtered() -> None:
    # GIVEN another scope
    # WHEN it is parsed
    result = parse_ocint_commit("a", 1, "nvim: Update plugin")

    # THEN it is omitted
    assert result is None


@pytest.mark.parametrize("subject", ["ocint:Add feature", "ocint: ", "Ocint: feature", "ocint feature"])
def test_malformed_ocint_prefix_is_rejected(subject: str) -> None:
    # GIVEN an almost-ocint prefix
    # WHEN/THEN it is parsed
    with pytest.raises(ReleaseError, match="Malformed"):
        parse_ocint_commit("a", 1, subject)


def test_changelog_is_newest_first_in_utc() -> None:
    # GIVEN commits supplied out of order
    commits = [Commit("a" * 40, 1, "Older"), Commit("b" * 40, 2, "Newer (#7)")]

    # WHEN a section is rendered
    section = changelog_section(SemVer(0, 2, 0), commits)

    # THEN timestamps are deterministic UTC and newest is first
    expected_date = datetime.fromtimestamp(2, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    assert section.index("Newer (#7)") < section.index("Older")
    assert expected_date in section


def test_changelog_prepends_without_rewriting_history() -> None:
    # GIVEN an existing changelog
    existing = "# ocint changelog\n\n## 0.1.0\n\n- baseline\n"

    # WHEN the next release is generated
    result = updated_changelog(existing, SemVer(0, 2, 0), [Commit("a" * 40, 1, "Feature")])

    # THEN the prior section remains after the new section
    assert result.count("# ocint changelog") == 1
    assert result.index("## 0.2.0") < result.index("## 0.1.0")
    assert result.endswith("- baseline\n")
