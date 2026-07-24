from __future__ import annotations

from typing import TYPE_CHECKING

from ocint.daemon.opencode.config import OpenCodeConfig, OpenCodeRuntimeConfig

if TYPE_CHECKING:
    from ocint.daemon.opencode.service import OpenCodeClient


def create_opencode_client(config: OpenCodeRuntimeConfig) -> OpenCodeClient:
    from ocint.daemon.opencode.service import OpenCodeClient

    return OpenCodeClient(config)


__all__ = ["OpenCodeConfig", "OpenCodeRuntimeConfig", "create_opencode_client"]
