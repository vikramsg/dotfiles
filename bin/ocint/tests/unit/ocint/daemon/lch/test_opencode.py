from pathlib import Path

import click
import pytest
from ocint.daemon.lch.opencode import (
    PrivateFilePurpose,
    PrivateFileRequirement,
    validate_private_file,
)


def test_private_file_validation_canonicalizes_parent_alias(tmp_path: Path) -> None:
    # GIVEN
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    parent_alias = tmp_path / "alias"
    parent_alias.symlink_to(real_parent, target_is_directory=True)
    target = real_parent / "daemon.toml"
    target.write_text("private")
    target.chmod(0o600)

    # WHEN
    validated = validate_private_file(
        PrivateFileRequirement(
            path=parent_alias / "daemon.toml",
            purpose=PrivateFilePurpose.DAEMON_CONFIG,
        )
    )

    # THEN
    assert validated.path == target


def test_private_file_validation_rejects_file_symlink(tmp_path: Path) -> None:
    # GIVEN
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    target = real_parent / "daemon.toml"
    target.write_text("private")
    target.chmod(0o600)
    file_alias = real_parent / "linked.toml"
    file_alias.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="non-symlink"):
        validate_private_file(PrivateFileRequirement(path=file_alias, purpose=PrivateFilePurpose.DAEMON_CONFIG))


def test_private_file_validation_rejects_non_private_mode(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "opencode.json"
    source.write_text("{}")
    source.chmod(0o644)

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="mode-0600"):
        validate_private_file(
            PrivateFileRequirement(
                path=source,
                purpose=PrivateFilePurpose.SOURCE_OPENCODE_CONFIG,
            )
        )
