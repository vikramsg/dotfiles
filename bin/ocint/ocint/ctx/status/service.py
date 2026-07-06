from pathlib import Path

from ocint.ctx.models import CtxSource, CtxStatus
from ocint.ctx.status.repository import CtxStatusRepository


def get_status(
    repository: CtxStatusRepository | None,
    *,
    ctx_db_path: Path,
) -> CtxStatus:
    if repository is None:
        return CtxStatus(db_path=ctx_db_path, db_exists=False)
    return repository.status()


def list_sources(repository: CtxStatusRepository | None) -> list[CtxSource]:
    if repository is None:
        return []
    return repository.sources()
