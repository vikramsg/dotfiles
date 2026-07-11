import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "validate_pr_title.py"
SPEC = importlib.util.spec_from_file_location("validate_pr_title", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SCOPES = MODULE.SCOPES
validate_pr_title = MODULE.validate_pr_title


@pytest.mark.parametrize("scope", SCOPES)
def test_all_allowed_scopes_are_accepted(scope: str) -> None:
    # GIVEN an explicitly allowed scope
    title = f"{scope}: useful summary"

    # WHEN the title is validated
    error = validate_pr_title(title)

    # THEN it is valid
    assert error is None


@pytest.mark.parametrize(
    "title",
    [
        "docs: summary",
        "OCINT: summary",
        "ocint:summary",
        "ocint: ",
        " ocint: summary",
        "ocint: summary ",
        "ocint: first\nsecond",
    ],
)
def test_invalid_titles_are_rejected(title: str) -> None:
    # GIVEN a title outside the exact convention
    # WHEN the title is validated
    error = validate_pr_title(title)

    # THEN validation explains the failure
    assert error is not None


def test_shell_syntax_is_inert_title_data() -> None:
    # GIVEN shell syntax in an otherwise valid summary
    title = "ocint: preserve $(touch /tmp/nope); $HOME"

    # WHEN the title is validated
    error = validate_pr_title(title)

    # THEN it remains ordinary text
    assert error is None
