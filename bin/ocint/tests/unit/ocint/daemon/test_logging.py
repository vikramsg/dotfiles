import stat
import threading
import time
from pathlib import Path

import pytest
from ocint.daemon.config import LoggingConfig
from ocint.daemon.logging import (
    DaemonLogSettings,
    close,
    configure,
    daemon_log_settings,
    follow_log,
    get_logger,
    read_log_tail,
)


def test_daemon_log_is_private_human_readable_and_single_line(tmp_path: Path) -> None:
    # GIVEN
    settings = daemon_log_settings(tmp_path / "state", LoggingConfig())
    configure(settings)
    logger = get_logger("test")

    # WHEN
    logger.info("job failed", job="job-1", error="first line\nsecond line")
    close()

    # THEN
    rendered = settings.path.read_text()
    assert " INFO  job failed " in rendered
    assert "job=job-1" in rendered
    assert 'error="first line\\nsecond line"' in rendered
    assert len(rendered.splitlines()) == 1
    assert stat.S_IMODE(settings.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.path.parent.stat().st_mode) == 0o700


def test_rotating_handler_retains_only_configured_private_backups(tmp_path: Path) -> None:
    # GIVEN
    settings = DaemonLogSettings(path=tmp_path / "daemon.log", max_bytes=1024, backups=2)
    configure(settings)
    logger = get_logger("rotation")

    # WHEN
    for number in range(60):
        logger.info("rotation event", number=number, payload="x" * 80)
    close()

    # THEN
    paths = (settings.path, tmp_path / "daemon.log.1", tmp_path / "daemon.log.2")
    assert all(path.is_file() for path in paths)
    assert not (tmp_path / "daemon.log.3").exists()
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths)


def test_log_tail_reads_rotated_files_in_chronological_order(tmp_path: Path) -> None:
    # GIVEN
    settings = DaemonLogSettings(path=tmp_path / "daemon.log", max_bytes=1024, backups=2)
    (tmp_path / "daemon.log.2").write_text("oldest\n")
    (tmp_path / "daemon.log.1").write_text("middle\n")
    settings.path.write_text("newest\n")

    # WHEN
    rendered = read_log_tail(settings, 2)

    # THEN
    assert rendered == "middle\nnewest\n"


def test_logging_rejects_symlink_destination(tmp_path: Path) -> None:
    # GIVEN
    target = tmp_path / "target"
    target.write_text("")
    path = tmp_path / "daemon.log"
    path.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(RuntimeError, match="regular mode-0600"):
        configure(DaemonLogSettings(path=path, max_bytes=1024, backups=2))


def test_log_path_uses_xdg_state_home(tmp_path: Path) -> None:
    # GIVEN / WHEN
    settings = daemon_log_settings(tmp_path / "state", LoggingConfig(max_bytes=2048, backup_count=2))

    # THEN
    assert settings.path == tmp_path / "state" / "ocint" / "daemon.log"
    assert settings.max_bytes == 2048
    assert settings.backups == 2


def test_log_follow_reopens_active_file_after_rotation(tmp_path: Path) -> None:
    # GIVEN
    settings = DaemonLogSettings(path=tmp_path / "daemon.log", max_bytes=1024, backups=2)
    configure(settings)
    logger = get_logger("follow")
    logger.info("initial event")
    follower = follow_log(settings, 1)
    assert "initial event" in next(follower)
    received: list[str] = []

    def consume() -> None:
        for text in follower:
            received.append(text)
            if "final event" in text:
                return

    consuming = threading.Thread(target=consume)
    consuming.start()
    time.sleep(0.3)

    # WHEN
    for number in range(30):
        logger.info("filler event", number=number, payload="x" * 80)
    logger.info("final event")
    consuming.join(timeout=5)
    follower.close()
    close()

    # THEN
    assert not consuming.is_alive()
    assert any("final event" in text for text in received)
    assert (tmp_path / "daemon.log.1").is_file()
