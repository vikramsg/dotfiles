import base64
import fcntl
import os
from pathlib import Path
import pty
import subprocess
import termios


PBCOPY_SCRIPT = Path(__file__).parents[3] / "bin" / "pbcopy"


def _read_available_pty_bytes(master_fd: int) -> bytes:
    os.set_blocking(master_fd, False)
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(master_fd, 4096)
        except (BlockingIOError, OSError):
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def test_pbcopy_writes_single_line_osc52_sequence_to_tty_stdout() -> None:
    # Input long enough that GNU base64 wraps at 76 columns unless stripped.
    sample_text = ("review comment line with unicode: café — " * 4) + "\nsecond line"
    master_fd, slave_fd = pty.openpty()
    try:
        try:
            result = subprocess.run(
                ["bash", str(PBCOPY_SCRIPT)],
                input=sample_text.encode("utf-8"),
                stdout=slave_fd,
                stderr=subprocess.PIPE,
                env={**os.environ, "OSTYPE": "linux-gnu"},
                start_new_session=True,
                timeout=5,
                check=False,
            )
        finally:
            os.close(slave_fd)

        pty_output = _read_available_pty_bytes(master_fd)
    finally:
        os.close(master_fd)

    expected_frame = f"\x1b]52;c;{base64.b64encode(sample_text.encode()).decode()}\x07".encode()
    assert result.returncode == 0
    assert pty_output == expected_frame


def test_pbcopy_falls_back_to_controlling_tty_when_stdout_is_redirected() -> None:
    sample_text = "copied via controlling tty"
    master_fd, slave_fd = pty.openpty()

    def attach_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    try:
        try:
            result = subprocess.run(
                ["bash", str(PBCOPY_SCRIPT)],
                input=sample_text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "OSTYPE": "linux-gnu"},
                preexec_fn=attach_controlling_tty,
                pass_fds=(slave_fd,),
                timeout=5,
                check=False,
            )
        finally:
            os.close(slave_fd)

        pty_output = _read_available_pty_bytes(master_fd)
    finally:
        os.close(master_fd)

    expected_frame = f"\x1b]52;c;{base64.b64encode(sample_text.encode()).decode()}\x07".encode()
    assert result.returncode == 0
    assert result.stdout == b""
    assert pty_output == expected_frame


def test_pbcopy_fails_cleanly_when_no_terminal_is_available() -> None:
    result = subprocess.run(
        ["bash", str(PBCOPY_SCRIPT)],
        input=b"headless background daemon text",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "OSTYPE": "linux-gnu"},
        start_new_session=True,
        timeout=5,
        check=False,
    )

    assert result.returncode != 0
    assert result.stdout == b""
