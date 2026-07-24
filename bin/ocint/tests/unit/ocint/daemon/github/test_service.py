from ocint.daemon.github.service import marker


def test_marker_is_stable_and_outcome_specific() -> None:
    # GIVEN / WHEN
    first = marker("owner/repo", 7, "addressed", 12)
    repeated = marker("owner/repo", 7, "addressed", 12)
    error = marker("owner/repo", 7, "closed-pr", 12)

    # THEN
    assert first == repeated
    assert first != error
