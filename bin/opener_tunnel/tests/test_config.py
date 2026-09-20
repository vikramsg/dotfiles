from pathlib import Path

import pytest

from opener_tunnel.config import (
    ConfigError,
    build_ssh_argv,
    get_config_file,
    load_config,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_repository_config_parses_and_expands_socket_path(monkeypatch, tmp_path):
    # Guards against shipping an unparseable config. Individual values are covered by the
    # fake-config tests below rather than restated from the repository's own config file.
    monkeypatch.setenv("HOME", str(tmp_path))

    config = load_config(REPOSITORY_ROOT / "opener_tunnel/config.toml")

    assert config.socket_path == tmp_path / ".opener.sock"


def test_config_override_and_ssh_argv_order(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
socket_path = "~/local.sock"

[browser]
command = ["browser", "--new"]

[tmux]
session = "test-tunnel"
command = ["tmux", "-L", "test-server"]

[ssh]
command = "test-ssh"
args = ["-N", "-T"]

[vm]
host = "vm-test"
socket_path = "/home/test/remote.sock"
""".strip()
        + "\n"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENER_TUNNEL_CONFIG_FILE", str(config_file))

    config = load_config()

    assert config.socket_path == tmp_path / "local.sock"
    assert build_ssh_argv(config) == [
        "test-ssh",
        "-N",
        "-T",
        "-R",
        f"/home/test/remote.sock:{tmp_path}/local.sock",
        "vm-test",
    ]


def test_default_config_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENER_TUNNEL_CONFIG_FILE", raising=False)

    assert get_config_file() == tmp_path / ".config/opener-tunnel/config.toml"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "socket_path must be a non-empty string"),
        (
            """
socket_path = "~/socket"
[browser]
command = []
[tmux]
session = "session"
command = ["tmux"]
[ssh]
command = "ssh"
args = []
[vm]
host = "vm"
socket_path = "/tmp/socket"
""",
            "browser.command must be a non-empty array of strings",
        ),
    ],
)
def test_rejects_missing_or_malformed_required_values(tmp_path, contents, message):
    config_file = tmp_path / "config.toml"
    config_file.write_text(contents)

    with pytest.raises(ConfigError, match=message):
        load_config(config_file)
