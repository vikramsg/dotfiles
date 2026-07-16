import builtins
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, and_, or_, select, update

from ocint.daemon.db.schema import outbox
from ocint.daemon.models import OutboxItem, WorkSource, WorkUpdate


class OutboxRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def claim(self, owner: str, lease_seconds: int, limit: int = 20) -> builtins.list[OutboxItem]:
        now = datetime.now(UTC)
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            rows = (
                connection.execute(
                    select(outbox)
                    .where(
                        and_(
                            outbox.c.delivered_at == "",
                            outbox.c.available_at <= now.isoformat(),
                            or_(outbox.c.lease_id == "", outbox.c.lease_expires_at <= now.isoformat()),
                        )
                    )
                    .order_by(outbox.c.available_at)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
            claimed: builtins.list[OutboxItem] = []
            for row in rows:
                lease_id = uuid.uuid4().hex
                connection.execute(
                    update(outbox)
                    .where(
                        and_(
                            outbox.c.id == row["id"],
                            or_(outbox.c.lease_id == "", outbox.c.lease_expires_at <= now.isoformat()),
                        )
                    )
                    .values(
                        lease_id=lease_id,
                        lease_owner=owner,
                        lease_expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
                    )
                )
                claimed.append(
                    OutboxItem(
                        id=str(row["id"]),
                        job_id=str(row["job_id"]),
                        source=WorkSource(str(row["source"])),
                        delivery_adapter=str(row["delivery_adapter"]),
                        delivery_target=str(row["delivery_target"]),
                        lease_id=lease_id,
                        conversation_id=str(row["conversation_id"]),
                        update=WorkUpdate.model_validate_json(str(row["payload"])),
                    )
                )
            connection.commit()
            return claimed
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acknowledge(self, outbox_id: str, lease_id: str, error: str = "") -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            if error:
                result = connection.execute(
                    update(outbox)
                    .where(
                        and_(
                            outbox.c.id == outbox_id,
                            outbox.c.lease_id == lease_id,
                            outbox.c.lease_expires_at > now.isoformat(),
                        )
                    )
                    .values(
                        attempts=outbox.c.attempts + 1,
                        available_at=(now + timedelta(seconds=1)).isoformat(),
                        last_error=error[:2000],
                        lease_id="",
                        lease_owner="",
                        lease_expires_at="",
                    )
                )
            else:
                result = connection.execute(
                    update(outbox)
                    .where(
                        and_(
                            outbox.c.id == outbox_id,
                            outbox.c.lease_id == lease_id,
                            outbox.c.lease_expires_at > now.isoformat(),
                        )
                    )
                    .values(
                        delivered_at=now.isoformat(),
                        lease_id="",
                        lease_owner="",
                        lease_expires_at="",
                    )
                )
            return result.rowcount == 1

    def renew(self, item: OutboxItem, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(outbox)
                .where(
                    and_(
                        outbox.c.id == item.id,
                        outbox.c.lease_id == item.lease_id,
                        outbox.c.delivered_at == "",
                        outbox.c.lease_expires_at > now.isoformat(),
                    )
                )
                .values(lease_expires_at=(now + timedelta(seconds=lease_seconds)).isoformat())
            )
            return result.rowcount == 1
