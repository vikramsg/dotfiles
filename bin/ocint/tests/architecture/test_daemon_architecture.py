from pathlib import Path


def test_daemon_has_only_deep_modules() -> None:
    # GIVEN
    daemon = Path(__file__).parents[2] / "ocint" / "daemon"

    # WHEN
    modules = {path.name for path in daemon.glob("*.py")}

    # THEN
    assert modules == {
        "__init__.py",
        "api.py",
        "cli.py",
        "config.py",
        "git.py",
        "github.py",
        "opencode.py",
        "repository.py",
        "service.py",
    }


def test_obsolete_daemon_deployment_and_helper_files_are_absent() -> None:
    # GIVEN
    package = Path(__file__).parents[2]

    # WHEN
    obsolete = [
        package / "systemd" / "ocint-daemon.service",
        package / "systemd" / "ocint-opencode.service",
        package / "systemd" / "ocint.conf",
        package / "config" / "git-publisher.config",
        package / "ocint" / "daemon" / "composition.py",
        package / "ocint" / "daemon" / "runtime.py",
        package / "ocint" / "daemon" / "run.py",
        package / "ocint" / "daemon" / "models.py",
    ]

    # THEN
    assert not any(path.exists() for path in obsolete)
