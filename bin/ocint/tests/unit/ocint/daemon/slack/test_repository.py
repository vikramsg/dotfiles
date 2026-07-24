from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.slack.models import StoredSlackThread
from ocint.daemon.slack.repository import SlackRepository


def test_reopen_requires_closed_same_channel_repository_and_single_open_alias(tmp_path: Path) -> None:
    # GIVEN
    engine = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(engine)
    repository = SlackRepository(engine)
    previous = repository.upsert_thread(
        StoredSlackThread(
            channel_id="C1",
            root_ts="1.000",
            workspace_id="T1",
            logical_source_id="slack:T1:C1:1.000",
            root_identity="slack:T1:C1:1.000",
            configured_repository="dotfiles",
            title="Work",
            authorized=True,
            closed=False,
        )
    )

    # WHEN / THEN
    with pytest.raises(ValueError, match="closed root"):
        repository.reopen(previous, "T1", "C1", "2.000", "dotfiles")
    repository.close("C1", "1.000")
    closed = repository.by_root("T1", "C1", "1.000")
    assert closed is not None
    with pytest.raises(ValueError, match="same configured channel"):
        repository.reopen(closed, "T2", "C1", "2.000", "dotfiles")
    with pytest.raises(ValueError, match="same configured channel"):
        repository.reopen(closed, "T1", "C2", "2.000", "dotfiles")
    with pytest.raises(ValueError, match="same configured channel"):
        repository.reopen(closed, "T1", "C1", "2.000", "other")
    reopened = repository.reopen(closed, "T1", "C1", "2.000", "dotfiles")
    assert reopened.logical_source_id == previous.logical_source_id
    with pytest.raises(ValueError, match="already open"):
        repository.reopen(closed, "T1", "C1", "3.000", "dotfiles")
    engine.dispose()
