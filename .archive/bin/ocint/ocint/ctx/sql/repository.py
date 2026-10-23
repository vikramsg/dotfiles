from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from ocint.ctx.sql.models import CtxSqlConfig, CtxSqlStableView


class CtxSqlRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def load_stable_projection_rows(self, config: CtxSqlConfig) -> dict[str, list[dict[str, object]]]:
        return {view.name: self._load_projection_rows(view) for view in config.stable_views}

    def _load_projection_rows(self, view: CtxSqlStableView) -> list[dict[str, object]]:
        column_sql = ", ".join(_quote_identifier(column.name) for column in view.columns)
        rows = self._session.execute(text(f"SELECT {column_sql} FROM {_quote_identifier(view.name)}")).mappings()
        return [dict(row) for row in rows]


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
