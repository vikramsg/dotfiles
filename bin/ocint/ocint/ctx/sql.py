from typing import Any

from ocint.ctx.repository import CtxSqlRepository
from ocint.ctx.schema import STABLE_CTX_VIEWS

ALLOWED_CTX_VIEWS = STABLE_CTX_VIEWS


def run_ctx_sql(repository: CtxSqlRepository, sql: str) -> list[dict[str, Any]]:
    return repository.execute_stable_view_query(sql)
