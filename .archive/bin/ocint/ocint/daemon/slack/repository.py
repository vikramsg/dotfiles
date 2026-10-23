from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.engine import RowMapping

from ocint.daemon.db.schema import slack_channel, slack_message, slack_reply, slack_thread
from ocint.daemon.models import MessageClassification
from ocint.daemon.slack.models import StoredSlackThread


class SlackRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def watermark(self, channel_id: str) -> str:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(slack_channel.c.watermark).where(slack_channel.c.channel_id == channel_id)
            ).scalar_one_or_none()
        return str(value or "")

    def set_watermark(self, channel_id: str, watermark: str) -> None:
        with self.engine.begin() as connection:
            identity = slack_channel.c.channel_id == channel_id
            if connection.execute(select(slack_channel.c.channel_id).where(identity)).first() is None:
                connection.execute(
                    insert(slack_channel).values(channel_id=channel_id, watermark=watermark, retry_not_before="")
                )
            else:
                connection.execute(
                    update(slack_channel).where(identity).values(watermark=watermark, retry_not_before="")
                )

    def defer(self, channel_id: str, retry_after_seconds: int) -> None:
        deadline = (datetime.now(UTC) + timedelta(seconds=retry_after_seconds)).isoformat()
        with self.engine.begin() as connection:
            identity = slack_channel.c.channel_id == channel_id
            if connection.execute(select(slack_channel.c.channel_id).where(identity)).first() is None:
                connection.execute(
                    insert(slack_channel).values(channel_id=channel_id, watermark="", retry_not_before=deadline)
                )
            else:
                connection.execute(update(slack_channel).where(identity).values(retry_not_before=deadline))

    def deferred(self, channel_id: str) -> bool:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(slack_channel.c.retry_not_before).where(slack_channel.c.channel_id == channel_id)
            ).scalar_one_or_none()
        return bool(value) and datetime.fromisoformat(str(value)) > datetime.now(UTC)

    def upsert_thread(self, value: StoredSlackThread) -> StoredSlackThread:
        with self.engine.begin() as connection:
            identity = (slack_thread.c.channel_id == value.channel_id) & (slack_thread.c.root_ts == value.root_ts)
            row = connection.execute(select(slack_thread).where(identity)).mappings().one_or_none()
            if row is None:
                values = value.model_dump()
                values["authorized"] = int(value.authorized)
                values["closed"] = int(value.closed)
                values["reopen_root"] = int(value.reopen_root)
                connection.execute(insert(slack_thread).values(**values))
                return value
            return self._thread(row)

    def thread(self, logical_source_id: str) -> StoredSlackThread | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(slack_thread)
                    .where(slack_thread.c.logical_source_id == logical_source_id)
                    .order_by(slack_thread.c.closed, slack_thread.c.root_ts.desc())
                )
                .mappings()
                .first()
            )
        return self._thread(row) if row is not None else None

    def by_root(self, workspace_id: str, channel_id: str, root_ts: str) -> StoredSlackThread | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(slack_thread).where(
                        slack_thread.c.workspace_id == workspace_id,
                        slack_thread.c.channel_id == channel_id,
                        slack_thread.c.root_ts == root_ts,
                    )
                )
                .mappings()
                .one_or_none()
            )
        return self._thread(row) if row is not None else None

    def open_threads(self, channel_id: str) -> tuple[StoredSlackThread, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(slack_thread).where(slack_thread.c.channel_id == channel_id, slack_thread.c.closed == 0)
            ).mappings()
            return tuple(self._thread(row) for row in rows)

    def reopen(
        self,
        previous: StoredSlackThread,
        workspace_id: str,
        channel_id: str,
        root_ts: str,
        configured_repository: str,
    ) -> StoredSlackThread:
        connection = self.engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            existing = (
                connection.execute(
                    select(slack_thread).where(
                        slack_thread.c.workspace_id == workspace_id,
                        slack_thread.c.channel_id == channel_id,
                        slack_thread.c.root_ts == root_ts,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                value = self._thread(existing)
                if value.logical_source_id != previous.logical_source_id:
                    raise ValueError("Slack root is already mapped to another logical thread")
                connection.commit()
                return value
            target = (
                connection.execute(
                    select(slack_thread).where(
                        slack_thread.c.workspace_id == previous.workspace_id,
                        slack_thread.c.channel_id == previous.channel_id,
                        slack_thread.c.root_ts == previous.root_ts,
                    )
                )
                .mappings()
                .one()
            )
            if (
                previous.workspace_id != workspace_id
                or previous.channel_id != channel_id
                or previous.configured_repository != configured_repository
                or not bool(target["closed"])
            ):
                raise ValueError("Slack reopen target must be a closed root in the same configured channel")
            open_alias = connection.execute(
                select(slack_thread.c.root_ts).where(
                    slack_thread.c.logical_source_id == previous.logical_source_id,
                    slack_thread.c.closed == 0,
                )
            ).first()
            if open_alias is not None:
                raise ValueError("Slack logical thread is already open")
            value = previous.model_copy(
                update={
                    "root_ts": root_ts,
                    "root_identity": self.root_identity(workspace_id, channel_id, root_ts),
                    "closed": False,
                    "reopen_root": True,
                }
            )
            values = value.model_dump()
            values["authorized"] = int(value.authorized)
            values["closed"] = 0
            values["reopen_root"] = 1
            connection.execute(insert(slack_thread).values(**values))
            connection.commit()
            return value
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self, channel_id: str, root_ts: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(slack_thread)
                .where(slack_thread.c.channel_id == channel_id, slack_thread.c.root_ts == root_ts)
                .values(closed=1)
            )

    def upsert_message(
        self, channel_id: str, root_ts: str, ts: str, user_id: str, body: str, classification: MessageClassification
    ) -> None:
        with self.engine.begin() as connection:
            identity = (slack_message.c.channel_id == channel_id) & (slack_message.c.ts == ts)
            values = {
                "channel_id": channel_id,
                "root_ts": root_ts,
                "ts": ts,
                "user_id": user_id,
                "body": body,
                "classification": classification.value,
            }
            if connection.execute(select(slack_message.c.ts).where(identity)).first() is None:
                connection.execute(insert(slack_message).values(**values))

    def reply_ts(self, key: str) -> str:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(slack_reply.c.ts).where(slack_reply.c.idempotency_key == key)
            ).scalar_one_or_none()
        return str(value or "")

    def begin_reply(self, key: str, channel_id: str) -> str:
        with self.engine.begin() as connection:
            value = connection.execute(
                select(slack_reply.c.ts).where(slack_reply.c.idempotency_key == key)
            ).scalar_one_or_none()
            if value is None:
                connection.execute(insert(slack_reply).values(idempotency_key=key, channel_id=channel_id, ts=""))
                return ""
            return str(value)

    def save_reply(self, key: str, channel_id: str, ts: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(slack_reply)
                .where(slack_reply.c.idempotency_key == key, slack_reply.c.channel_id == channel_id)
                .values(ts=ts)
            )

    @staticmethod
    def root_identity(workspace_id: str, channel_id: str, root_ts: str) -> str:
        return f"slack:{workspace_id}:{channel_id}:{root_ts}"

    @staticmethod
    def _thread(row: RowMapping) -> StoredSlackThread:
        return StoredSlackThread(**{field: row[field] for field in StoredSlackThread.model_fields})
