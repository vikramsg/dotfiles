from pathlib import Path
import tempfile

import pytest


@pytest.fixture
def socket_directory():
    # macOS Unix socket paths cannot fit pytest's descriptive per-test directories.
    with tempfile.TemporaryDirectory(prefix="od-") as directory:
        yield Path(directory)
