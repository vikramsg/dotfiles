from pathlib import Path

import pytest
from ocint.daemon.coordinator import CoordinatorConfig
from pydantic import ValidationError


def test_coordinator_config_matches_production_toml_and_rejects_unsafe_access(tmp_path: Path) -> None:
    # GIVEN
    raw = {
        "workspace_root": tmp_path / "coordinator",
        "turn_timeout_seconds": 1_800,
        "shutdown_timeout_seconds": 30,
        "orphan_retention_seconds": 86_400,
        "retry_seconds": 5,
        "response_chunk_characters": 3_500,
        "slack_post_interval_seconds": 1,
        "ingress": {
            "host": "127.0.0.1",
            "port": 8_733,
            "max_request_bytes": 65_536,
            "timestamp_tolerance_seconds": 300,
        },
        "slack": {
            "workspace_id": "T1",
            "channels": [{"channel_id": "C1", "authorized_users": ["U1"]}],
        },
        "opencode": {
            "server_url": "http://127.0.0.1:4098",
            "config_file": tmp_path / "opencode.json",
            "xdg_config_home": tmp_path / "opencode-xdg",
            "xdg_data_home": tmp_path / "opencode-data",
        },
    }

    # WHEN
    config = CoordinatorConfig.model_validate(raw)

    # THEN
    assert config.workspace_root == (tmp_path / "coordinator").resolve()
    assert config.slack.channels[0].authorized_users == frozenset(("U1",))
    assert config.slack.required_scopes == frozenset(("channels:history", "chat:write"))
    assert config.ingress.processing_timeout_seconds == 2.5
    assert config.ingress.database_busy_timeout_ms == 2_000
    assert config.max_turn_retries == 3
    with pytest.raises(ValidationError, match="loopback"):
        CoordinatorConfig.model_validate({**raw, "ingress": {**raw["ingress"], "host": "0.0.0.0"}})
    with pytest.raises(ValidationError, match="unique"):
        CoordinatorConfig.model_validate(
            {
                **raw,
                "slack": {
                    "workspace_id": "T1",
                    "channels": [raw["slack"]["channels"][0], raw["slack"]["channels"][0]],
                },
            }
        )


def test_coordinator_config_preserves_a_lexical_workspace_path_with_a_symlink_component(tmp_path: Path) -> None:
    # GIVEN
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(target, target_is_directory=True)

    # WHEN
    config = CoordinatorConfig.model_validate(
        {
            "workspace_root": link / "coordinator",
            "turn_timeout_seconds": 1_800,
            "shutdown_timeout_seconds": 30,
            "orphan_retention_seconds": 86_400,
            "retry_seconds": 5,
            "response_chunk_characters": 3_500,
            "slack_post_interval_seconds": 1,
            "ingress": {"host": "127.0.0.1", "port": 8_733},
            "slack": {
                "workspace_id": "T1",
                "channels": [{"channel_id": "C1", "authorized_users": ["U1"]}],
            },
            "opencode": {
                "server_url": "http://127.0.0.1:4098",
                "config_file": tmp_path / "opencode.json",
                "xdg_config_home": tmp_path / "opencode-xdg",
                "xdg_data_home": tmp_path / "opencode-data",
            },
        }
    )

    # THEN
    assert config.workspace_root == link / "coordinator"
    assert config.workspace_root != target / "coordinator"


@pytest.mark.parametrize(
    ("processing_timeout_seconds", "database_busy_timeout_ms"),
    [(0, 100), (3, 100), (1, 0), (1, 1_001)],
)
def test_coordinator_ingress_rejects_an_unsafe_processing_budget(
    tmp_path: Path, processing_timeout_seconds: float, database_busy_timeout_ms: int
) -> None:
    # GIVEN
    ingress = {
        "host": "127.0.0.1",
        "port": 8_733,
        "processing_timeout_seconds": processing_timeout_seconds,
        "database_busy_timeout_ms": database_busy_timeout_ms,
    }

    # WHEN / THEN
    with pytest.raises(ValidationError, match="timeout"):
        CoordinatorConfig.model_validate(
            {
                "workspace_root": tmp_path / "coordinator",
                "turn_timeout_seconds": 1_800,
                "shutdown_timeout_seconds": 30,
                "orphan_retention_seconds": 86_400,
                "retry_seconds": 5,
                "response_chunk_characters": 3_500,
                "slack_post_interval_seconds": 1,
                "ingress": ingress,
                "slack": {
                    "workspace_id": "T1",
                    "channels": [{"channel_id": "C1", "authorized_users": ["U1"]}],
                },
                "opencode": {
                    "server_url": "http://127.0.0.1:4098",
                    "config_file": tmp_path / "opencode.json",
                    "xdg_config_home": tmp_path / "opencode-xdg",
                    "xdg_data_home": tmp_path / "opencode-data",
                },
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn_timeout_seconds", 0),
        ("shutdown_timeout_seconds", 0),
        ("orphan_retention_seconds", 0),
        ("retry_seconds", 0),
        ("max_turn_retries", 0),
        ("response_chunk_characters", 3_501),
        ("slack_post_interval_seconds", 0),
    ],
)
def test_coordinator_config_rejects_nonpositive_or_oversized_policy(tmp_path: Path, field: str, value: int) -> None:
    # GIVEN
    raw = {
        "workspace_root": tmp_path / "coordinator",
        "turn_timeout_seconds": 1_800,
        "shutdown_timeout_seconds": 30,
        "orphan_retention_seconds": 86_400,
        "retry_seconds": 5,
        "response_chunk_characters": 3_500,
        "slack_post_interval_seconds": 1,
        "ingress": {"host": "127.0.0.1", "port": 8_733},
        "slack": {
            "workspace_id": "T1",
            "channels": [{"channel_id": "C1", "authorized_users": ["U1"]}],
        },
        "opencode": {
            "server_url": "http://127.0.0.1:4098",
            "config_file": tmp_path / "opencode.json",
            "xdg_config_home": tmp_path / "opencode-xdg",
            "xdg_data_home": tmp_path / "opencode-data",
        },
    }

    # WHEN / THEN
    with pytest.raises(ValidationError):
        CoordinatorConfig.model_validate({**raw, field: value})
