from ocint._timeutil import make_window
from ocint.opencode.repository import OpenCodeRepository
from ocint.state.service import StateService

from tests.fixtures.opencode_db import create_opencode_db


def test_state_summary_counts_only_step_finish_parts(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    service = StateService(OpenCodeRepository(db_path))

    summary = service.summary(make_window())

    assert summary.sessions == 2
    assert summary.llm_steps == 2
    assert summary.cost == 3.75
    assert summary.tokens.input == 11
    assert summary.tokens.output == 22
    assert summary.tokens.total == 51


def test_state_model_usage_uses_message_metadata(tmp_path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    service = StateService(OpenCodeRepository(db_path))

    rows = service.models(make_window())

    assert [(row.provider, row.model, row.cost) for row in rows] == [
        ("openai", "gpt-5.5", 2.5),
        ("anthropic", "claude-sonnet-4-5", 1.25),
    ]
