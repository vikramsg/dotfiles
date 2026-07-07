"""Shared ctx history read-model SQL; repository modules own execution."""

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from ocint.ctx.models import CtxSearchCandidate

CandidateOrder = Literal["ASC", "DESC"]


def candidate_query_sql(
    *,
    predicate_sql: str,
    order: CandidateOrder,
    include_limit: bool,
    with_sql: str = "",
    join_sql: str = "",
    order_prefix_sql: str = "",
) -> str:
    limit_sql = "LIMIT :limit" if include_limit else ""
    return f"""
            {with_sql}
            SELECT e.id AS event_pk,
                   e.source_id AS source_id,
                   e.provider AS provider,
                   coalesce(e.provider_session_id, '') AS session_id,
                   s.parent_id AS parent_id,
                   e.event_id AS event_id,
                   e.source_table AS source_table,
                   e.message_id AS message_id,
                   e.event_type AS event_type,
                   e.time_created AS time_created,
                   e.time_updated AS time_updated,
                   s.title AS title,
                   s.workspace AS workspace,
                   e.source_path AS source_path,
                   e.full_text AS full_text,
                   e.search_text AS search_text,
                   e.citation AS citation,
                   src.source_path AS source_db_path
            FROM ctx_event AS e
            LEFT JOIN ctx_session AS s
              ON s.source_id = e.source_id
             AND s.provider_session_id = e.provider_session_id
            JOIN ctx_source AS src ON src.id = e.source_id
            {join_sql}
            WHERE {predicate_sql}
            ORDER BY {order_prefix_sql} coalesce(e.time_created, 0) {order}, e.source_table {order}, e.event_id {order}
            {limit_sql}
            """


def candidate_rows(rows: Iterable[Mapping[Any, Any]]) -> list[CtxSearchCandidate]:
    return [CtxSearchCandidate.model_validate(row) for row in rows]


def session_summary_sql(*, predicate_sql: str, include_limit: bool) -> str:
    limit_sql = "LIMIT :limit" if include_limit else ""
    return f"""
                SELECT s.id AS session_pk,
                       s.source_id AS source_id,
                       s.provider AS provider,
                       s.provider_session_id AS session_id,
                       s.parent_id AS parent_id,
                       s.title AS title,
                       s.workspace AS workspace,
                       s.time_created AS time_created,
                       s.time_updated AS time_updated,
                       src.source_path AS source_db_path,
                       count(e.id) AS event_count
                 FROM ctx_session AS s
                 JOIN ctx_source AS src ON src.id = s.source_id
                 LEFT JOIN ctx_refresh_state AS refresh ON refresh.source_id = src.id
                 LEFT JOIN ctx_event AS e
                   ON e.source_id = s.source_id
                  AND e.provider_session_id = s.provider_session_id
                 WHERE {predicate_sql}
                 GROUP BY s.id
                  ORDER BY coalesce(refresh.latest_success_completed_at, 0) DESC, s.id DESC
                  {limit_sql}
                  """
