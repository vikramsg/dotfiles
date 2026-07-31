from dataclasses import dataclass, field
from pathlib import Path

import pytest
from ocint.daemon.db import create_daemon_engine
from ocint.daemon.db.schema import metadata
from ocint.daemon.models import MessageClassification, ReplyOutcome, ReplyRequest
from ocint.daemon.slack.client import SlackRateLimited
from ocint.daemon.slack.config import SlackChannelConfig, SlackConfig
from ocint.daemon.slack.models import (
    SlackAuth,
    SlackHistory,
    SlackMessage,
    SlackMessages,
    SlackPostedMessage,
    StoredSlackThread,
)
from ocint.daemon.slack.repository import SlackRepository
from ocint.daemon.slack.service import SlackContext, SlackService
from sqlalchemy import Engine


@dataclass
class FakeSlackTransport:
    roots: list[SlackMessage]
    thread_messages: list[SlackMessage]
    posted: list[str] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)
    history_oldest: list[str] = field(default_factory=list)
    client_message_ids: list[str] = field(default_factory=list)
    fail_after_post: bool = False
    rate_limited: bool = False

    async def auth_test(self) -> SlackAuth:
        return SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1")

    async def history(self, channel: str, oldest: str = "", cursor: str = "") -> SlackHistory:
        del channel, cursor
        self.history_oldest.append(oldest)
        if self.rate_limited:
            raise SlackRateLimited(60)
        return SlackHistory(messages=SlackMessages(root=self.roots))

    async def replies(self, channel: str, root_ts: str, cursor: str = "") -> SlackHistory:
        del channel, root_ts, cursor
        return SlackHistory(messages=SlackMessages(root=self.thread_messages))

    async def post_message(self, channel: str, thread_ts: str, text: str, client_msg_id: str) -> SlackPostedMessage:
        del channel, thread_ts
        self.posted.append(text)
        self.client_message_ids.append(client_msg_id)
        self.thread_messages.append(
            SlackMessage(ts="3.000", text=text, user="UBOT", bot_id="BBOT", client_msg_id=client_msg_id)
        )
        if self.fail_after_post:
            raise RuntimeError("crash after remote post")
        return SlackPostedMessage(ts="3.000")

    async def add_reaction(self, channel: str, timestamp: str, name: str) -> None:
        del channel, timestamp
        if name not in self.reactions:
            self.reactions.append(name)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    value = create_daemon_engine(tmp_path / "control.sqlite")
    metadata.create_all(value)
    return value


@pytest.mark.asyncio
async def test_authorized_private_channel_thread_and_completion_are_durable(engine: Engine) -> None:
    # GIVEN
    old = SlackMessage(ts="0.999", text="Old request", user="U1")
    root = SlackMessage(ts="1.000", thread_ts="1.000", text="Change the config\nKeep compatibility", user="U1")
    transport = FakeSlackTransport(roots=[old, root], thread_messages=[root])
    repository = SlackRepository(engine)
    service = SlackService(
        context=SlackContext(
            config=SlackConfig(
                workspace_id="T1",
                channels=(
                    SlackChannelConfig(
                        channel_id="C1",
                        repository="dotfiles",
                        authorized_users=frozenset(("U1",)),
                        initial_oldest="1.000",
                    ),
                ),
            ),
            auth=SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1"),
            client=transport,
            repository=repository,
        )
    )

    # WHEN
    observations = await service.observe()
    thread = observations.root[0]
    await service.reply(
        ReplyRequest(
            source_thread_id=thread.source_id,
            source_anchor_id=thread.messages.root[0].source_id,
            outcome=ReplyOutcome.ADDRESSED,
            text="Issue addressed: https://example.test/pr/1",
        )
    )
    await service.reply(
        ReplyRequest(
            source_thread_id=thread.source_id,
            source_anchor_id=thread.messages.root[0].source_id,
            outcome=ReplyOutcome.ADDRESSED,
            text="Issue addressed: https://example.test/pr/1",
        )
    )

    # THEN
    assert thread.title == "Change the config"
    assert thread.messages.root[0].body == root.text
    assert thread.messages.root[0].classification is MessageClassification.ACTIONABLE
    assert transport.posted == ["Issue addressed: https://example.test/pr/1"]
    assert transport.reactions == ["white_check_mark"]
    assert transport.history_oldest == ["1.000"]
    assert repository.open_threads("C1") == ()


@pytest.mark.asyncio
async def test_unauthorized_human_is_classified_for_reply_without_work(engine: Engine) -> None:
    # GIVEN
    root = SlackMessage(ts="1.000", text="Do something", user="U2")
    transport = FakeSlackTransport(roots=[root], thread_messages=[root])
    service = SlackService(
        context=SlackContext(
            config=SlackConfig(
                workspace_id="T1",
                channels=(
                    SlackChannelConfig(
                        channel_id="C1",
                        repository="dotfiles",
                        authorized_users=frozenset(("U1",)),
                        initial_oldest="1.000",
                    ),
                ),
            ),
            auth=SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1"),
            client=transport,
            repository=SlackRepository(engine),
        )
    )

    # WHEN
    thread = (await service.observe()).root[0]

    # THEN
    assert not thread.eligible
    assert thread.messages.root[0].classification is MessageClassification.UNAUTHORIZED


@pytest.mark.asyncio
async def test_pending_reply_recovers_remote_message_before_reaction_and_close(engine: Engine) -> None:
    # GIVEN
    root = SlackMessage(ts="1.000", text="Change", user="U1")
    transport = FakeSlackTransport(roots=[root], thread_messages=[root], fail_after_post=True)
    repository = SlackRepository(engine)
    service = SlackService(
        context=SlackContext(
            config=SlackConfig(
                workspace_id="T1",
                channels=(
                    SlackChannelConfig(
                        channel_id="C1",
                        repository="dotfiles",
                        authorized_users=frozenset(("U1",)),
                        initial_oldest="1.000",
                    ),
                ),
            ),
            auth=SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1"),
            client=transport,
            repository=repository,
        )
    )
    thread = (await service.observe()).root[0]
    request = ReplyRequest(
        source_thread_id=thread.source_id,
        source_anchor_id=thread.messages.root[0].source_id,
        outcome=ReplyOutcome.CLOSED_PULL_REQUEST,
        text="The owned pull request is closed.",
    )
    with pytest.raises(RuntimeError, match="crash after remote post"):
        await service.reply(request)

    # WHEN
    transport.fail_after_post = False
    await service.reply(request)

    # THEN
    assert transport.posted == ["The owned pull request is closed."]
    assert transport.reactions == ["white_check_mark"]
    assert repository.open_threads("C1") == ()


def test_canonical_permalink_parser_accepts_copied_and_mrkdwn_links() -> None:
    # GIVEN / WHEN
    direct = SlackService._reopen_target("reopen https://workspace.slack.com/archives/C123/p1753380000123456")
    wrapped = SlackService._reopen_target("reopen <https://workspace.slack.com/archives/C123/p1753380000123456>")

    # THEN
    assert direct is not None
    assert direct.channel_id == "C123"
    assert direct.root_ts == "1753380000.123456"
    assert wrapped == direct


@pytest.mark.asyncio
async def test_unauthorized_reopen_cannot_alias_closed_thread(engine: Engine) -> None:
    # GIVEN
    repository = SlackRepository(engine)
    original = repository.upsert_thread(
        StoredSlackThread(
            channel_id="C1",
            root_ts="1753380000.123456",
            workspace_id="T1",
            logical_source_id="slack:T1:C1:1753380000.123456",
            root_identity="slack:T1:C1:1753380000.123456",
            configured_repository="dotfiles",
            title="Original",
            authorized=True,
            closed=True,
        )
    )
    command = SlackMessage(
        ts="1753380001.123456",
        text="reopen https://workspace.slack.com/archives/C1/p1753380000123456",
        user="U2",
    )
    transport = FakeSlackTransport(roots=[command], thread_messages=[command])
    service = SlackService(
        context=SlackContext(
            config=SlackConfig(
                workspace_id="T1",
                channels=(
                    SlackChannelConfig(
                        channel_id="C1",
                        repository="dotfiles",
                        authorized_users=frozenset(("U1",)),
                        initial_oldest=command.ts,
                    ),
                ),
            ),
            auth=SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1"),
            client=transport,
            repository=repository,
        )
    )

    # WHEN
    observed = (await service.observe()).root[0]

    # THEN
    assert observed.source_id != original.logical_source_id
    assert not observed.eligible
    target = repository.by_root("T1", "C1", original.root_ts)
    assert target is not None
    assert target.closed


@pytest.mark.asyncio
async def test_rate_limit_defer_survives_service_restart_without_sleep_or_calls(engine: Engine) -> None:
    # GIVEN
    transport = FakeSlackTransport(roots=[], thread_messages=[], rate_limited=True)
    repository = SlackRepository(engine)
    context = SlackContext(
        config=SlackConfig(
            workspace_id="T1",
            channels=(
                SlackChannelConfig(
                    channel_id="C1",
                    repository="dotfiles",
                    authorized_users=frozenset(("U1",)),
                    initial_oldest="1753380000.123456",
                ),
            ),
        ),
        auth=SlackAuth(user_id="UBOT", bot_id="BBOT", team_id="T1"),
        client=transport,
        repository=repository,
    )
    first = SlackService(context=context)
    assert (await first.observe()).root == []

    # WHEN
    transport.rate_limited = False
    restarted = SlackService(context=context)
    observations = await restarted.observe()

    # THEN
    assert observations.root == []
    assert transport.history_oldest == ["1753380000.123456"]
    assert repository.deferred("C1")
