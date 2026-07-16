import hashlib
import hmac
import json
import time

import pytest
from ocint.daemon.channels import ManualChannel, SlackChannel
from ocint.daemon.models import WorkRequest, WorkSource


@pytest.mark.asyncio
async def test_manual_channel_transports_normalized_requests() -> None:
    # GIVEN a concrete manual channel containing a request
    received: list[WorkRequest] = []
    channel = ManualChannel(received.append)
    expected = WorkRequest(
        idempotency_key="manual-1",
        conversation_id="conversation-1",
        actor="actor",
        repository="repo",
        text="make a change",
        source=WorkSource.MANUAL,
        delivery_adapter="manual",
        delivery_target="manual",
    )
    await channel.enqueue(expected)
    await channel.close()

    # WHEN its durable submission loop is consumed
    await channel.run()

    # THEN the normalized request is preserved
    assert received == [expected]


def test_slack_channel_verifies_signature_and_normalizes_payload() -> None:
    # GIVEN a correctly signed Slack event for an explicitly mapped channel
    secret = "signing-secret"
    timestamp = str(int(time.time()))
    body = json.dumps(
        {
            "event_id": "Ev1",
            "team_id": "T1",
            "event": {"channel": "C1", "user": "U1", "text": "fix it", "ts": "1.2"},
        }
    ).encode()
    digest = hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    accepted: list[WorkRequest] = []
    channel = SlackChannel("http://127.0.0.1", "token", secret, {"C1": "repo"}, accepted.append)

    # WHEN the adapter receives the protocol payload
    request = channel.submit_signed(timestamp, f"v0={digest}", body)

    # THEN transport details become a channel-independent request
    assert request.idempotency_key == "slack:T1:Ev1"
    assert request.repository == "repo"
    assert request.source is WorkSource.SLACK
    assert accepted == [request]
