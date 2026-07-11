import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class ReleaseWorkspace:
    root: Path
    remote: Path
    environment: dict[str, str]
    baseline_remote_head: str
    baseline_remote_refs: str


@pytest.fixture
def release_workspace(tmp_path: Path) -> ReleaseWorkspace:
    """Provide disposable real Git, uv workspace, and isolated tool directories."""
    root = tmp_path / "dotfiles"
    remote = tmp_path / "origin.git"
    package = root / "bin" / "ocint"
    scripts = package / "scripts"
    module = package / "ocint"
    scripts.mkdir(parents=True)
    module.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "fixture-root"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n'
        '[tool.uv.workspace]\nmembers = ["bin/ocint"]\n[tool.uv]\npackage = false\n'
    )
    (package / "pyproject.toml").write_text(
        '[project]\nname = "ocint"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n'
        'dependencies = ["click"]\n[project.scripts]\nocint = "ocint.cli:main"\n'
        '[build-system]\nrequires = ["uv_build>=0.9.26,<0.10.0"]\nbuild-backend = "uv_build"\n'
        '[tool.uv.build-backend]\nmodule-root = "."\n'
    )
    (module / "__init__.py").write_text('"""fixture"""\n')
    (module / "cli.py").write_text(
        "import click\n\n@click.command()\n@click.version_option(package_name='ocint', message='%(prog)s %(version)s')\n"
        "def main():\n    pass\n"
    )
    (package / "justfile").write_text("test:\n    @true\ncheck:\n    @true\nsmoke:\n    @true\n")
    source_script = Path(__file__).parents[2] / "scripts" / "ocint_release.py"
    shutil.copy2(source_script, scripts / "ocint_release.py")
    (root / "README.md").write_text("baseline\n")
    subprocess.run(["uv", "lock"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "release@example.test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "chore: baseline"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "tag", "-a", "ocint-v0.1.0", "-m", "ocint v0.1.0"], cwd=root, check=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main", "--tags"], cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("baseline\nocint feature\n")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "ocint: Add safe release flow (#12)"], cwd=root, check=True, capture_output=True
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=root, check=True, capture_output=True)
    remote_head = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    remote_refs = subprocess.run(
        ["git", "--git-dir", str(remote), "for-each-ref", "--format=%(refname) %(objectname)"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    home = tmp_path / "home"
    tool_dir = tmp_path / "tools"
    tool_bin = tmp_path / "tool-bin"
    cache = tmp_path / "cache"
    home.mkdir()
    tool_dir.mkdir()
    tool_bin.mkdir()
    cache.mkdir()
    environment = {
        **os.environ,
        "HOME": str(home),
        "UV_TOOL_DIR": str(tool_dir),
        "UV_TOOL_BIN_DIR": str(tool_bin),
        "UV_CACHE_DIR": str(cache),
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "project-environment"),
        "PATH": f"{tool_bin}{os.pathsep}{os.environ['PATH']}",
    }
    return ReleaseWorkspace(root, remote, environment, remote_head, remote_refs)
