from dataclasses import dataclass

import aiohttp
import pytest
from ocint.daemon.lch.preflight import (
    StaticEndpointClassifier,
    StaticEndpointPreflightClient,
    StaticEndpointPreflightConfig,
    StaticEndpointProbe,
    StaticEndpointState,
    require_static_endpoint_offline,
)


@dataclass
class FakeTransport:
    response: StaticEndpointProbe | None = None
    error: Exception | None = None
    requested_endpoint: str = ""

    async def get(self, endpoint: str, config: StaticEndpointPreflightConfig) -> StaticEndpointProbe:
        self.requested_endpoint = endpoint
        assert config.timeout_seconds == 2
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.mark.parametrize(
    ("probe", "expected"),
    [
        (StaticEndpointProbe(status=404, body=b"offline ERR_NGROK_3200 domain"), StaticEndpointState.OFFLINE),
        (StaticEndpointProbe(status=405, body=b""), StaticEndpointState.COLLISION),
        (StaticEndpointProbe(status=404, body=b"different ngrok response"), StaticEndpointState.COLLISION),
        (StaticEndpointProbe(status=502, body=b"backend unavailable"), StaticEndpointState.COLLISION),
    ],
)
def test_classifier_distinguishes_ngrok_offline_response_from_collision(
    probe: StaticEndpointProbe,
    expected: StaticEndpointState,
) -> None:
    # GIVEN
    config = StaticEndpointPreflightConfig(timeout_seconds=2)

    # WHEN
    state = StaticEndpointClassifier(config).classify(probe)

    # THEN
    assert state is expected


@pytest.mark.asyncio
async def test_client_uses_bounded_request_and_allows_only_offline_domain() -> None:
    # GIVEN
    config = StaticEndpointPreflightConfig(timeout_seconds=2)
    transport = FakeTransport(StaticEndpointProbe(status=404, body=b"ERR_NGROK_3200"))
    client = StaticEndpointPreflightClient(transport, StaticEndpointClassifier(config), config)

    # WHEN
    await require_static_endpoint_offline("https://secret-domain.example.test/slack/events", client)

    # THEN
    assert transport.requested_endpoint == "https://secret-domain.example.test/slack/events"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "message"),
    [
        (
            FakeTransport(StaticEndpointProbe(status=200, body=b"recognizable-private-backend-body")),
            "active tunnel or backend",
        ),
        (FakeTransport(error=aiohttp.ClientConnectionError()), "could not verify"),
    ],
)
async def test_preflight_fails_closed_without_exposing_endpoint_or_response(
    transport: FakeTransport,
    message: str,
) -> None:
    # GIVEN
    config = StaticEndpointPreflightConfig(timeout_seconds=2)
    client = StaticEndpointPreflightClient(transport, StaticEndpointClassifier(config), config)

    # WHEN / THEN
    with pytest.raises(RuntimeError, match=message) as failure:
        await require_static_endpoint_offline("https://recognizable-secret-domain.example.test/events", client)
    assert "recognizable-secret-domain" not in str(failure.value)
    assert "recognizable-private-backend-body" not in str(failure.value)
