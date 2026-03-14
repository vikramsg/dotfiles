from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from bin.ghostty_workspace.ghostty_workspace.cli import (
    WorkspaceConfig,
    WorkspaceTab,
    _build_tab_shell_command,
    load_workspace_config,
    main,
    render_applescript,
)


def test_load_workspace_config_resolves_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace_dir = home / ".config" / "ghostty" / "workspaces"
    workspace_dir.mkdir(parents=True)
    config_file = workspace_dir / "dev.toml"
    config_file.write_text(
        "\n".join(
            [
                'path = "~/Projects/demo"',
                "focus_tab = 2",
                "",
                "[[tabs]]",
                'name = "tab1"',
                'command = "nvim"',
                "",
                "[[tabs]]",
                'name = "tab2"',
                'path = "./api"',
            ]
        )
    )

    monkeypatch.setattr("bin.ghostty_workspace.ghostty_workspace.cli.WORKSPACES_DIR", workspace_dir)
    monkeypatch.setenv("HOME", str(home))

    cfg = load_workspace_config(workspace_name="dev")

    assert cfg.focus_tab == 2
    assert cfg.tabs[0].path == home / "Projects" / "demo"
    assert cfg.tabs[1].path == home / "Projects" / "demo" / "api"


def test_render_applescript_uses_focus_and_tabs():
    cfg = WorkspaceConfig(
        focus_tab=2,
        tabs=[
            WorkspaceTab(name="tab1", command="true", path=Path("/tmp")),
            WorkspaceTab(name="tab2", command=None, path=Path("/tmp")),
        ],
    )

    script = render_applescript(cfg)

    assert "set cfg1 to new surface configuration" in script
    assert "set cfg2 to new surface configuration" in script
    assert "new tab in win with configuration cfg2" in script
    assert 'perform action "set_tab_title:tab1"' in script
    assert 'perform action "set_tab_title:tab2"' in script
    assert 'perform action "goto_tab:2" on terminal 1 of selected tab of win' in script
    assert "delay 0.1" in script
    assert "select tab (tab" not in script
    assert "DISABLE_AUTO_TITLE=true" not in script
    assert "\\033]0;" not in script


def test_render_applescript_preserves_toml_tab_order():
    cfg = WorkspaceConfig(
        focus_tab=1,
        tabs=[
            WorkspaceTab(name="dotfiles", command="ssh vm.dotfiles", path=Path("~")),
            WorkspaceTab(name="knda", command="ssh vm.kunda", path=Path("~")),
            WorkspaceTab(name="mx", command="ssh vm.mx", path=Path("~")),
            WorkspaceTab(name="btop", command="ssh vm.btop", path=Path("~")),
        ],
    )

    script = render_applescript(cfg)

    dotfiles_idx = script.index("dotfiles")
    knda_idx = script.index("knda")
    mx_idx = script.index("mx")
    btop_idx = script.index("btop")

    assert dotfiles_idx < knda_idx < mx_idx < btop_idx


def test_cli_runs_osascript_with_rendered_script(tmp_path):
    config_file = tmp_path / "workspace.toml"
    config_file.write_text(
        "\n".join(
            [
                "focus_tab = 1",
                "",
                "[[tabs]]",
                'name = "shell"',
            ]
        )
    )

    runner = CliRunner()
    with patch("bin.ghostty_workspace.ghostty_workspace.cli.subprocess.run") as run_mock:
        result = runner.invoke(main, ["--config", str(config_file)])

    assert result.exit_code == 0
    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "osascript"
    assert cmd[1] == "-e"


def test_build_tab_shell_command_keeps_shell_open_without_legacy_title_hacks():
    cmd = _build_tab_shell_command(
        WorkspaceTab(name="tabA", command="ls -la", path=Path("/tmp"))
    )

    assert "DISABLE_AUTO_TITLE=true" not in cmd
    assert "GHOSTTY_SHELL_FEATURES" not in cmd
    assert "\\033]0;" not in cmd
    assert "cd /tmp" in cmd
    assert "ls -la" in cmd
    assert "exec" in cmd
    assert "$SHELL" in cmd
    assert "-l" in cmd


def test_render_applescript_escapes_set_tab_title_payload():
    cfg = WorkspaceConfig(
        focus_tab=1,
        tabs=[
            WorkspaceTab(name='qa "alpha" \\ tab', command=None, path=Path("/tmp")),
        ],
    )

    script = render_applescript(cfg)

    assert 'perform action "set_tab_title:qa \\"alpha\\" \\\\ tab"' in script


def test_focus_tab_out_of_bounds_fails(tmp_path):
    config_file = tmp_path / "bad.toml"
    config_file.write_text(
        "\n".join(
            [
                "focus_tab = 2",
                "",
                "[[tabs]]",
                'name = "only"',
            ]
        )
    )

    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_file)])

    assert result.exit_code != 0
    assert "focus_tab must be between 1 and 1" in result.output
