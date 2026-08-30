from pathlib import Path

import pytest
from pydantic import ValidationError


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

    from lch.config import CommandService

    configured_service = config.services["lch-opener-tunnel"]
    assert isinstance(configured_service, CommandService)
    assert configured_service.command == ("opener-tunnel", "run")

    from lch.jobs import get_launchd_job_definition

    service = get_launchd_job_definition("lch-opener-tunnel")
    assert service.label == "com.example.dotfiles.lch-opener-tunnel"
    assert service.service == configured_service


def test_repository_toml_loads_with_configured_service():
    from lch.config import ApplicationService, CommandService, MacOSApplication, load_config

    config = load_config(REPOSITORY_ROOT / "lch/config.toml")

    assert config.namespace == "com.vikramsg.dotfiles"
    assert isinstance(config.services["lch-opener-tunnel"], CommandService)
    macflow = config.services["lch-macflow"]
    assert isinstance(macflow, ApplicationService)
    assert isinstance(macflow.application, MacOSApplication)
    assert macflow.application.path == Path.home() / "Applications/Macflow.app"


def test_load_config_accepts_reserved_linux_application(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
namespace = "com.example"

[services.example.application]
type = "linux"
path = "~/.local/share/applications/example.desktop"
""".strip()
        + "\n"
    )

    from lch.config import ApplicationService, LinuxApplication, load_config

    service = load_config(config_file).services["example"]
    assert isinstance(service, ApplicationService)
    assert isinstance(service.application, LinuxApplication)
    assert service.application.path == Path.home() / ".local/share/applications/example.desktop"


@pytest.mark.parametrize(
    "service_body",
    [
        "",
        'command = []',
        'command = ["example", ""]',
        'command = ["example"]\napplication = {type = "macos", path = "/Applications/Example.app"}',
        'application = {path = "/Applications/Example.app"}',
        'application = {type = "windows", path = "C:/Example.exe"}',
        'application = {type = "macos", path = ""}',
        'application = {type = "macos", path = "/Applications/Example.app", typo = true}',
    ],
)
def test_load_config_rejects_invalid_service_shapes(tmp_path, service_body):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f'namespace = "com.example"\n\n[services.example]\n{service_body}\n'
    )

    from lch.config import load_config

    with pytest.raises(ValidationError):
        load_config(config_file)
