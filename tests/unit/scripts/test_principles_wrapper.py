import json
import stat
import subprocess
from pathlib import Path

WRAPPER_PATH = Path(__file__).parents[3] / "bin" / "principles"


def _make_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _make_fake_mise(fake_bin: Path, ruby_prefix: Path) -> Path:
    return _make_executable(
        fake_bin / "mise",
        f"#!/usr/bin/env bash\n"
        f'if [ "$1" = "where" ] && [ "$2" = "ruby@3.4" ]; then echo "{ruby_prefix}"; exit 0; fi\n'
        f"exit 1\n",
    )


def test_wrapper_isolates_env_and_forwards_args(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    ruby_prefix = tmp_path / "ruby-3.4"
    xdg_data_home = tmp_path / "xdg-data"
    gem_dir = xdg_data_home / "principles-gem"

    _make_fake_mise(fake_bin, ruby_prefix)
    _make_executable(
        ruby_prefix / "bin" / "ruby",
        '#!/usr/bin/env python3\n'
        'import json, os, sys\n'
        'print(json.dumps({\n'
        '    "argv": sys.argv[1:],\n'
        '    "gem_home": os.environ.get("GEM_HOME"),\n'
        '    "gem_path": os.environ.get("GEM_PATH"),\n'
        '    "rubyopt": os.environ.get("RUBYOPT"),\n'
        '    "rubylib": os.environ.get("RUBYLIB"),\n'
        '    "bundle_gemfile": os.environ.get("BUNDLE_GEMFILE"),\n'
        '    "path_first": os.environ.get("PATH", "").split(":")[0],\n'
        '}))\n',
    )
    principles_bin = _make_executable(gem_dir / "bin" / "principles", "#!/usr/bin/env ruby\n")

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "XDG_DATA_HOME": str(xdg_data_home),
        "GEM_HOME": "/tmp/polluted-gem-home",
        "GEM_PATH": "/tmp/polluted-gem-path",
        "RUBYOPT": "-rbundler/setup",
        "RUBYLIB": "/tmp/polluted-rubylib",
        "BUNDLE_GEMFILE": "/tmp/polluted/Gemfile",
    }

    result = subprocess.run(
        [str(WRAPPER_PATH), "list-principles", "--project", "/tmp/example"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["argv"] == [str(principles_bin), "list-principles", "--project", "/tmp/example"]
    assert payload["gem_home"] == str(gem_dir)
    assert payload["gem_path"] is None
    assert payload["rubyopt"] is None
    assert payload["rubylib"] is None
    assert payload["bundle_gemfile"] is None
    assert payload["path_first"] == str(gem_dir / "bin")


def test_wrapper_refuses_when_gem_is_missing(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    ruby_prefix = tmp_path / "ruby-3.4"
    xdg_data_home = tmp_path / "xdg-data"

    _make_fake_mise(fake_bin, ruby_prefix)
    _make_executable(ruby_prefix / "bin" / "ruby", "#!/usr/bin/env bash\nexit 0\n")

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "XDG_DATA_HOME": str(xdg_data_home),
    }

    result = subprocess.run(
        [str(WRAPPER_PATH), "--version"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "just principles" in result.stderr


def test_wrapper_refuses_when_ruby_34_is_not_installed(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    _make_executable(fake_bin / "mise", "#!/usr/bin/env bash\nexit 1\n")

    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
    }

    result = subprocess.run(
        [str(WRAPPER_PATH), "--version"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "ruby@3.4" in result.stderr
