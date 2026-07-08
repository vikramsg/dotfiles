import pytest


@pytest.fixture(autouse=True)
def default_ctx_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy ctx tests on SQLite unless a test explicitly selects DuckDB."""
    monkeypatch.setenv("OCINT_CTX_BACKEND", "sqlite")
