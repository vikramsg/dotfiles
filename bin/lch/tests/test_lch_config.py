from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def write_config(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'namespace = "{payload["namespace"]}"\n')
    return path


def test_load_config_reads_namespace_from_effective_file(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/lch/config.toml",
        {
            "namespace": "com.example.dotfiles",
        },
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.config import load_config

    config = load_config()

    assert config.namespace == "com.example.dotfiles"


def test_get_job_definition_uses_namespace_from_config(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path / ".config/lch/config.toml",
        {
            "namespace": "com.example.dotfiles",
        },
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_definition

    job = get_job_definition("lch-screenshot-clipboard")

    assert job.label == "com.example.dotfiles.lch-screenshot-clipboard"


def test_get_job_identity_uses_namespace_without_a_registered_job(
    tmp_path, monkeypatch
):
    config_file = write_config(
        tmp_path / ".config/lch/config.toml",
        {
            "namespace": "com.example.dotfiles",
        },
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.jobs import get_job_identity

    identity = get_job_identity("lch-example-watcher")

    assert identity.job_id == "lch-example-watcher"
    assert identity.label == "com.example.dotfiles.lch-example-watcher"


def test_load_config_uses_default_path_when_override_is_absent(tmp_path, monkeypatch):
    home = tmp_path / "home"
    config_file = write_config(
        home / ".config/lch/config.toml",
        {
            "namespace": "com.example.default",
        },
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LCH_CONFIG_FILE", raising=False)

    from lch.config import get_config_file, load_config

    assert get_config_file() == config_file
    assert load_config().namespace == "com.example.default"


def test_load_config_reads_commented_service(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
# Prefix used for labels.
namespace = "com.example.dotfiles"

[services.lch-opener-tunnel]
# Persistent domain command.
command = ["opener-tunnel", "run"]
""".strip()
        + "\n"
    )
    monkeypatch.setenv("LCH_CONFIG_FILE", str(config_file))

    from lch.config import load_config

    config = load_config(config_file)

    assert config.services == {"lch-opener-tunnel": ("opener-tunnel", "run")}

    from lch.jobs import get_launchd_job_definition

    service = get_launchd_job_definition("lch-opener-tunnel")
    assert service.label == "com.example.dotfiles.lch-opener-tunnel"
    assert service.dispatch_command == ["opener-tunnel", "run"]


def test_repository_toml_loads_with_configured_service():
    from lch.config import load_config

    config = load_config(REPOSITORY_ROOT / "lch/config.toml")

    assert config.namespace == "com.vikramsg.dotfiles"
    assert config.services["lch-opener-tunnel"] == ("opener-tunnel", "run")
