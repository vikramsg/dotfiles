import sqlite3
from pathlib import Path
from typing import cast

from ocint._timeutil import UsageWindow, make_window
from ocint.opencode.models import OpenCodeCacheTokens, OpenCodePartData, OpenCodePartRow, OpenCodeTokenPayload
from ocint.opencode.repository import OpenCodeRepository
from ocint.state.service import StateService
from tests.fixtures.opencode_db import create_opencode_db


def test_state_summary_counts_only_step_finish_parts(tmp_path: Path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    service = StateService(OpenCodeRepository(db_path))

    summary = service.summary(make_window())

    assert summary.sessions == 2
    assert summary.llm_steps == 2
    assert summary.cost == 3.75
    assert summary.tokens.input == 11
    assert summary.tokens.output == 22
    assert summary.tokens.total == 51


def test_state_model_usage_uses_message_metadata(tmp_path: Path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    service = StateService(OpenCodeRepository(db_path))

    rows = service.models(make_window())

    assert [(row.provider, row.model, row.cost) for row in rows] == [
        ("openai", "gpt-5.5", 2.5),
        ("anthropic", "claude-sonnet-4-5", 1.25),
    ]


def test_state_usage_parts_reads_time_window_batches_without_loading_all_parts() -> None:
    repository = _BatchOnlyRepository()
    service = StateService(cast(OpenCodeRepository, repository))

    summary = service.summary(UsageWindow(start_ms=10, end_ms=20))

    assert repository.calls == [(10, 20, 1_000)]
    assert summary.sessions == 1
    assert summary.llm_steps == 1
    assert summary.cost == 3.0
    assert summary.tokens.input == 7


def test_opencode_usage_part_batches_pushes_time_window_and_parses_batches(tmp_path: Path) -> None:
    db_path = create_opencode_db(tmp_path / "opencode.db")
    with sqlite3.connect(db_path) as connection:
        start_ms = int(connection.execute("SELECT timeCreated FROM part WHERE id = 'p-primary-patch'").fetchone()[0])
    repository = OpenCodeRepository(db_path)

    batches = list(repository.usage_part_batches(start_ms=start_ms, end_ms=start_ms + 1, batch_size=1))

    assert [[part.id for part in batch] for batch in batches] == [["p-primary-patch"]]
    assert batches[0][0].data.type == "file.patch"


class _BatchOnlyRepository:
    db_path = Path("/tmp/fake-opencode.db")

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int | None, int]] = []

    def parts(self) -> list[OpenCodePartRow]:
        raise AssertionError("StateService.summary should use usage_part_batches")

    def usage_part_batches(
        self,
        *,
        start_ms: int | None,
        end_ms: int | None,
        batch_size: int,
    ) -> list[list[OpenCodePartRow]]:
        self.calls.append((start_ms, end_ms, batch_size))
        return [
            [
                _part(
                    session_id="s-usage",
                    part_type="step-finish",
                    cost=3.0,
                    input_tokens=7,
                )
            ],
            [_part(session_id="s-ignored", part_type="text", cost=99.0, input_tokens=99)],
        ]


def _part(*, session_id: str, part_type: str, cost: float, input_tokens: int) -> OpenCodePartRow:
    return OpenCodePartRow(
        id=f"part-{part_type}-{session_id}",
        message_id="m-usage",
        session_id=session_id,
        time_created=10,
        time_updated=10,
        data=OpenCodePartData(
            type=part_type,
            cost=cost,
            tokens=OpenCodeTokenPayload(
                input=input_tokens,
                cache=OpenCodeCacheTokens(),
            ),
        ),
    )
