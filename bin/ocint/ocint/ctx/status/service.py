from ocint._errors import OcintError
from ocint.ctx.models import CtxSource, CtxStatus
from ocint.ctx.sql.models import CtxSqlConfig
from ocint.ctx.status.repository import CtxStatusRepository


def require_ctx_index_ready(repository: CtxStatusRepository, config: CtxSqlConfig, expected_revision: str) -> None:
    """Fail before read use cases query ctx tables that may not be migrated yet."""
    if not repository.index_ready(config, expected_revision):
        raise OcintError(f"ocint ctx index is not ready; run `ocint ctx import` first: {repository.db_path}")


def get_status(repository: CtxStatusRepository, config: CtxSqlConfig, expected_revision: str) -> CtxStatus:
    require_ctx_index_ready(repository, config, expected_revision)
    return repository.status()


def list_sources(repository: CtxStatusRepository, config: CtxSqlConfig, expected_revision: str) -> list[CtxSource]:
    require_ctx_index_ready(repository, config, expected_revision)
    return repository.sources()
