from pathlib import Path

import click
import pytest
from ocint.daemon.lch.opencode import (
    PrivateFilePurpose,
    PrivateFileRequirement,
    validate_opencode_source_file,
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


@pytest.mark.parametrize("purpose", [PrivateFilePurpose.DAEMON_CONFIG, PrivateFilePurpose.MANAGED_CONFIG])
def test_private_file_validation_rejects_file_symlink(tmp_path: Path, purpose: PrivateFilePurpose) -> None:
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
        validate_private_file(PrivateFileRequirement(path=file_alias, purpose=purpose))


@pytest.mark.parametrize("purpose", [PrivateFilePurpose.DAEMON_CONFIG, PrivateFilePurpose.MANAGED_CONFIG])
def test_private_file_validation_rejects_non_private_mode(tmp_path: Path, purpose: PrivateFilePurpose) -> None:
    # GIVEN
    source = tmp_path / "opencode.json"
    source.write_text("{}")
    source.chmod(0o644)

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="mode-0600"):
        validate_private_file(
            PrivateFileRequirement(
                path=source,
                purpose=purpose,
            )
        )


def test_source_opencode_validation_accepts_direct_mode_0600_file(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "opencode.json"
    source.write_text("{}")
    source.chmod(0o600)

    # WHEN
    validated = validate_opencode_source_file(source)

    # THEN
    assert validated.source_path == source
    assert validated.target_path == source
    assert not validated.is_symlink
    assert validated.target_mode == 0o600
    assert validated.content == "{}"


def test_source_opencode_validation_accepts_user_symlink_to_mode_0644_file(tmp_path: Path) -> None:
    # GIVEN
    target = tmp_path / "dotfiles" / "opencode.json"
    target.parent.mkdir()
    target.write_text("{}")
    target.chmod(0o644)
    source = tmp_path / "config" / "opencode.json"
    source.parent.mkdir()
    source.symlink_to(target)

    # WHEN
    validated = validate_opencode_source_file(source)

    # THEN
    assert validated.source_path == source
    assert validated.target_path == target
    assert validated.is_symlink
    assert validated.target_mode == 0o644
    assert validated.content == "{}"


def test_source_opencode_validation_rejects_broken_symlink(tmp_path: Path) -> None:
    # GIVEN
    source = tmp_path / "opencode.json"
    source.symlink_to(tmp_path / "missing.json")

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="target must resolve"):
        validate_opencode_source_file(source)


@pytest.mark.parametrize("mode", [0o620, 0o602])
def test_source_opencode_validation_rejects_group_or_other_writable_target(tmp_path: Path, mode: int) -> None:
    # GIVEN
    target = tmp_path / "target.json"
    target.write_text("{}")
    target.chmod(mode)
    source = tmp_path / "opencode.json"
    source.symlink_to(target)

    # WHEN / THEN
    with pytest.raises(click.ClickException, match="must not be writable by group or others"):
        validate_opencode_source_file(source)
