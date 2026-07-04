import sqlite3


def install_ctx_views(_connection: sqlite3.Connection) -> None:
    raise RuntimeError("ctx SQL views are migration-owned in the ocint ctx index; run `ocint ctx import` first")
