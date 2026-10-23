import json
import stat
from pathlib import Path

import pytest
from ocint.daemon.coordinator import CoordinatorWorkspaceConfig, RepositoryCatalogueEntry
from ocint.daemon.coordinator.workspace import CoordinatorWorkspace


def test_workspace_is_private_atomic_and_contains_only_the_safe_catalogue(tmp_path: Path) -> None:
    # GIVEN
    root = tmp_path / "coordinator"
    config = CoordinatorWorkspaceConfig(
        root=root,
        repositories=(
            RepositoryCatalogueEntry(
                name="dotfiles",
                description="Configuration",
                github_repository="owner/dotfiles",
                default_branch="main",
            ),
        ),
    )

    # WHEN
    CoordinatorWorkspace(config).generate()
    catalogue = json.loads((root / "repositories.json").read_text())

    # THEN
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "AGENTS.md").stat().st_mode) == 0o600
    assert stat.S_IMODE((root / "repositories.json").stat().st_mode) == 0o600
    assert catalogue == {
        "repositories": [
            {
                "default_branch": "main",
                "description": "Configuration",
                "github_repository": "owner/dotfiles",
                "name": "dotfiles",
            }
        ]
    }
    assert "local_path" not in (root / "repositories.json").read_text()


def test_workspace_refuses_a_symlink_target(tmp_path: Path) -> None:
    # GIVEN
    root = tmp_path / "coordinator"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("do not replace")
    (root / "AGENTS.md").symlink_to(outside)
    config = CoordinatorWorkspaceConfig(root=root, repositories=())

    # WHEN / THEN
    with pytest.raises(ValueError, match="not a regular file"):
        CoordinatorWorkspace(config).generate()
    assert outside.read_text() == "do not replace"


def test_workspace_refuses_a_symlink_component_in_the_lexical_configured_path(tmp_path: Path) -> None:
    # GIVEN
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    root = linked_parent / "coordinator"
    config = CoordinatorWorkspaceConfig(root=root, repositories=())

    # WHEN / THEN
    with pytest.raises(ValueError, match="symlink"):
        CoordinatorWorkspace(config).generate()
    assert not (outside / "coordinator").exists()
