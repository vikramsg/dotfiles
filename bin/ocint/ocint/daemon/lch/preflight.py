from enum import StrEnum
from typing import Protocol

import aiohttp
from pydantic import BaseModel, ConfigDict, Field


class StaticEndpointState(StrEnum):
    OFFLINE = "offline"
    COLLISION = "collision"
    UNAVAILABLE = "unavailable"


class StaticEndpointProbe(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: int = Field(ge=100, le=599)
    body: bytes


class StaticEndpointPreflightConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    timeout_seconds: float = Field(default=3, gt=0, le=10)
    max_response_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    offline_error_code: bytes = b"ERR_NGROK_3200"


class StaticEndpointTransport(Protocol):
    async def get(self, endpoint: str, config: StaticEndpointPreflightConfig) -> StaticEndpointProbe: ...


class AioHttpStaticEndpointTransport:
    async def get(self, endpoint: str, config: StaticEndpointPreflightConfig) -> StaticEndpointProbe:
        timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as client, client.get(endpoint) as response:
            body = await response.content.read(config.max_response_bytes + 1)
            if len(body) > config.max_response_bytes:
                body = body[: config.max_response_bytes]
            return StaticEndpointProbe(status=response.status, body=body)


class StaticEndpointClassifier:
    def __init__(self, config: StaticEndpointPreflightConfig) -> None:
        self.config = config

    def classify(self, probe: StaticEndpointProbe) -> StaticEndpointState:
        if probe.status == 404 and self.config.offline_error_code in probe.body:
            return StaticEndpointState.OFFLINE
        return StaticEndpointState.COLLISION


class StaticEndpointPreflightClient:
    def __init__(
        self,
        transport: StaticEndpointTransport,
        classifier: StaticEndpointClassifier,
        config: StaticEndpointPreflightConfig,
    ) -> None:
        self.transport = transport
        self.classifier = classifier
        self.config = config

    async def check(self, endpoint: str) -> StaticEndpointState:
        try:
            probe = await self.transport.get(endpoint, self.config)
        except aiohttp.ClientError, TimeoutError:
            return StaticEndpointState.UNAVAILABLE
        return self.classifier.classify(probe)


async def require_static_endpoint_offline(
    endpoint: str,
    client: StaticEndpointPreflightClient,
) -> None:
    state = await client.check(endpoint)
    if state is StaticEndpointState.OFFLINE:
        return
    if state is StaticEndpointState.COLLISION:
        raise RuntimeError("static endpoint preflight detected an active tunnel or backend")
    raise RuntimeError("static endpoint preflight could not verify that the domain is offline")
