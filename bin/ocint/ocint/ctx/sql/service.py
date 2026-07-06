from typing import Any

from ocint.ctx.schema import STABLE_CTX_VIEWS
from ocint.ctx.sql.repository import CtxSqlRepository

ALLOWED_CTX_VIEWS = STABLE_CTX_VIEWS


def run_ctx_sql(repository: CtxSqlRepository, sql: str) -> list[dict[str, Any]]:
    return repository.execute_stable_view_query(sql)
