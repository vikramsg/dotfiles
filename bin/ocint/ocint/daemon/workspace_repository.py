import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, and_, func, insert, or_, select, update

from ocint.daemon.db.schema import artifact, event, job, workspace
from ocint.daemon.models import WorkspaceRetirement


class WorkspaceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim_retirement(
        self,
        workspace_owner_id: str,
        worktree_path: str,
        owner: str,
        lease_seconds: int,
    ) -> WorkspaceRetirement | None:
        now = datetime.now(UTC)
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            lease_id = uuid.uuid4().hex
            result = connection.execute(
                update(workspace)
                .where(
                    and_(
                        workspace.c.id == workspace_owner_id,
                        workspace.c.worktree_path == worktree_path,
                        or_(
                            workspace.c.state == "active",
                            and_(
                                workspace.c.state == "retiring",
                                workspace.c.lease_expires_at <= now.isoformat(),
                            ),
                        ),
                    )
                )
                .values(
                    state="retiring",
                    lease_id=lease_id,
                    lease_owner=owner,
                    lease_expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
                    attempts=workspace.c.attempts + 1,
                    updated_at=now.isoformat(),
                )
            )
            if result.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
            return WorkspaceRetirement(
                workspace_owner_id=workspace_owner_id,
                worktree_path=Path(worktree_path),
                lease_id=lease_id,
                disposed=bool(
                    connection.scalar(select(workspace.c.disposed).where(workspace.c.id == workspace_owner_id))
                ),
                removed=bool(
                    connection.scalar(select(workspace.c.removed).where(workspace.c.id == workspace_owner_id))
                ),
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def renew(self, retirement: WorkspaceRetirement, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(workspace)
                .where(
                    and_(
                        workspace.c.id == retirement.workspace_owner_id,
                        workspace.c.state == "retiring",
                        workspace.c.lease_id == retirement.lease_id,
                        workspace.c.lease_expires_at > now.isoformat(),
                    )
                )
                .values(lease_expires_at=(now + timedelta(seconds=lease_seconds)).isoformat())
            )
            return result.rowcount == 1

    def complete(self, retirement: WorkspaceRetirement, error: str = "") -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            if error:
                result = connection.execute(
                    update(workspace)
                    .where(
                        and_(
                            workspace.c.id == retirement.workspace_owner_id,
                            workspace.c.state == "retiring",
                            workspace.c.lease_id == retirement.lease_id,
                            workspace.c.lease_expires_at > now.isoformat(),
                        )
                    )
                    .values(
                        state="active",
                        lease_id="",
                        lease_owner="",
                        lease_expires_at="",
                        last_error=error[:2000],
                        updated_at=now.isoformat(),
                    )
                )
                return result.rowcount == 1
            result = connection.execute(
                update(workspace)
                .where(
                    and_(
                        workspace.c.id == retirement.workspace_owner_id,
                        workspace.c.state == "retiring",
                        workspace.c.lease_id == retirement.lease_id,
                        workspace.c.lease_expires_at > now.isoformat(),
                        workspace.c.disposed == 1,
                        workspace.c.removed == 1,
                    )
                )
                .values(
                    state="retired",
                    worktree_path="",
                    lease_id="",
                    lease_owner="",
                    lease_expires_at="",
                    last_error="",
                    updated_at=now.isoformat(),
                )
            )
            if result.rowcount != 1:
                return False
            connection.execute(
                update(job)
                .where(
                    and_(
                        job.c.workspace_owner_id == retirement.workspace_owner_id,
                        job.c.worktree_path == str(retirement.worktree_path),
                    )
                )
                .values(worktree_path="", updated_at=now.isoformat())
            )
            existing = connection.scalar(
                select(func.count())
                .select_from(artifact)
                .where(
                    and_(
                        artifact.c.job_id == retirement.workspace_owner_id,
                        artifact.c.kind == "retired_worktree",
                    )
                )
            )
            if existing == 0:
                connection.execute(
                    insert(artifact).values(
                        id=uuid.uuid4().hex,
                        job_id=retirement.workspace_owner_id,
                        kind="retired_worktree",
                        value=str(retirement.worktree_path),
                        url="",
                        created_at=now.isoformat(),
                    )
                )
            connection.execute(
                insert(event).values(
                    job_id=retirement.workspace_owner_id,
                    attempt_id=None,
                    kind="worktree.retired",
                    payload=str(retirement.worktree_path),
                    created_at=now.isoformat(),
                )
            )
            return True

    def checkpoint(self, retirement: WorkspaceRetirement, *, disposed: bool, removed: bool) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(workspace)
                .where(
                    and_(
                        workspace.c.id == retirement.workspace_owner_id,
                        workspace.c.state == "retiring",
                        workspace.c.lease_id == retirement.lease_id,
                        workspace.c.lease_expires_at > now.isoformat(),
                    )
                )
                .values(disposed=int(disposed), removed=int(removed), updated_at=now.isoformat())
            )
            return result.rowcount == 1
