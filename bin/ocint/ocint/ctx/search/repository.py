from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ocint.ctx.history import candidate_query_sql, candidate_rows
from ocint.ctx.models import CtxSearchCandidate


class CtxSearchRepository:
    def __init__(self, session: Session, *, db_path: Path) -> None:
        self._session = session
        self.db_path = db_path

    def search_events(
        self,
        *,
        query_tokens: list[str],
        required_terms: list[str],
        since_ms: int | None,
        session_id: str | None,
        workspace: str | None,
        file_filter: str | None,
        include_subagents: bool,
        exclude_session_tree_root_id: str | None,
        limit: int | None,
    ) -> list[CtxSearchCandidate]:
        """Return already-filtered rows; required predicates are applied before LIMIT."""
        params: dict[str, Any] = {}
        where = ["1 = 1"]
        # Required query and term predicates are LIKE filters over imported
        # search_text. FTS rows are maintained during import, but must not narrow
        # substring matches such as "stable view" matching "stable views".
        _add_search_text_filters(where, params, query_tokens, prefix="query_token")
        _add_search_text_filters(where, params, required_terms, prefix="required_term")
        fts_query = _fts_query([*query_tokens, *required_terms])
        join_sql = ""
        order_prefix_sql = ""
        if fts_query:
            params["fts_query"] = fts_query
            # FTS is an optimization only: the WHERE clause above keeps LIKE
            # substring matching as the authoritative inclusion contract.
            join_sql = """
                LEFT JOIN (
                    SELECT event_pk
                    FROM ctx_event_fts
                    WHERE ctx_event_fts MATCH :fts_query
                    GROUP BY event_pk
                ) AS fts ON fts.event_pk = e.id
            """
            order_prefix_sql = "CASE WHEN fts.event_pk IS NULL THEN 0 ELSE 1 END DESC,"
        if since_ms is not None:
            where.append("e.time_created IS NOT NULL AND e.time_created >= :since_ms")
            params["since_ms"] = since_ms
        if session_id:
            where.append("e.provider_session_id = :session_id")
            params["session_id"] = session_id
        if workspace:
            where.append(
                "lower(coalesce(s.workspace, '') || ' ' || coalesce(s.title, '')) LIKE :workspace_filter ESCAPE '\\'"
            )
            params["workspace_filter"] = _like_pattern(workspace.lower())
        if file_filter:
            where.append(
                "EXISTS ("
                "SELECT 1 FROM ctx_file_touched ft "
                "WHERE ft.source_id = e.source_id "
                "AND ft.source_table = e.source_table "
                "AND ft.event_id = e.event_id "
                "AND lower(ft.path) LIKE :file_filter ESCAPE '\\')"
            )
            params["file_filter"] = _like_pattern(file_filter.lower())
        if not include_subagents:
            where.append("s.parent_id IS NULL")
        with_sql = ""
        if exclude_session_tree_root_id is not None:
            params["exclude_session_tree_root_id"] = exclude_session_tree_root_id
            # Seed from the active ID itself so root events are excluded even
            # when the imported root ctx_session row is absent; UNION preserves
            # cycle safety while recursing through imported child sessions.
            with_sql = """
                WITH RECURSIVE excluded_session_tree(session_id) AS (
                    SELECT :exclude_session_tree_root_id
                    WHERE :exclude_session_tree_root_id != ''
                    UNION
                    SELECT child.provider_session_id
                    FROM ctx_session AS child
                    JOIN excluded_session_tree AS parent
                      ON child.parent_id = parent.session_id
                    WHERE child.provider_session_id IS NOT NULL
                )
            """
            where.append("coalesce(e.provider_session_id, '') NOT IN (SELECT session_id FROM excluded_session_tree)")
        if limit is not None:
            params["limit"] = limit
        statement = text(
            candidate_query_sql(
                predicate_sql=" AND ".join(where),
                order="DESC",
                include_limit=limit is not None,
                with_sql=with_sql,
                join_sql=join_sql,
                order_prefix_sql=order_prefix_sql,
            )
        )
        return candidate_rows(self._session.execute(statement, params).mappings())


def _add_search_text_filters(where: list[str], params: dict[str, Any], values: Iterable[str], *, prefix: str) -> None:
    for index, value in enumerate(_unique_non_empty(values)):
        key = f"{prefix}_{index}"
        where.append(f"lower(e.search_text) LIKE :{key} ESCAPE '\\'")
        params[key] = _like_pattern(value.lower())


def _unique_non_empty(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _fts_query(values: Iterable[str]) -> str | None:
    phrases = [_fts_phrase(value) for value in _unique_non_empty(values) if _has_fts_token(value)]
    return " AND ".join(phrases) if phrases else None


def _fts_phrase(value: str) -> str:
    escaped = value.strip().replace('"', '""')
    return f'"{escaped}"'


def _has_fts_token(value: str) -> bool:
    return any(character.isalnum() or character == "_" for character in value)
