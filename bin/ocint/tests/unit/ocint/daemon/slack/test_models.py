import pytest
from ocint.daemon.slack.models import parse_slack_timestamp


def test_slack_timestamp_uses_exact_integer_ordering_without_float_rounding() -> None:
    # GIVEN
    timestamp = "9999999999.999999"

    # WHEN
    order = parse_slack_timestamp(timestamp)

    # THEN
    assert order == 9_999_999_999_999_999
    with pytest.raises(ValueError, match="invalid Slack timestamp"):
        parse_slack_timestamp("9999999999.1")
