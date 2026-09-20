import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader


WORKSPACES_DIR = Path.home() / ".config" / "ghostty" / "workspaces"
TEMPLATES_DIR = Path(__file__).parent / "templates"
APPLESCRIPT_TEMPLATE_NAME = "workspace.applescript.j2"


@dataclass
class WorkspaceTab:
    name: str
    command: str | None
    path: Path | None


@dataclass
class WorkspaceConfig:
    focus_tab: int
    tabs: list[WorkspaceTab]


def _applescript_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_tab_shell_command(tab: WorkspaceTab) -> str:
    steps: list[str] = []

    if tab.path is not None:
        steps.append(f"cd {shlex.quote(str(tab.path))}")

    if tab.command:
        steps.append(tab.command)

    steps.append('exec "$SHELL" -l')

    shell_script = "; ".join(steps)
    command = f"bash -lc {shlex.quote(shell_script)}"
    return _applescript_escape(command)


def _resolve_tab_path(tab_path: str | None, global_path: Path | None, config_dir: Path) -> Path | None:
    if tab_path is None:
        return global_path

    expanded = Path(tab_path).expanduser()
    if expanded.is_absolute():
        return expanded

    if global_path is not None:
        return (global_path / expanded).resolve()

    return (config_dir / expanded).resolve()


def load_workspace_config(*, workspace_name: str | None = None, config_path: Path | None = None) -> WorkspaceConfig:
    if workspace_name and config_path:
        raise click.ClickException("Use either a workspace name or --config, not both.")

    if config_path is None:
        if not workspace_name:
            raise click.ClickException("Provide a workspace name or use --config.")
        config_path = WORKSPACES_DIR / f"{workspace_name}.toml"

    if not config_path.exists():
        raise click.ClickException(f"Workspace config not found: {config_path}")

    with config_path.open("rb") as f:
        data = tomllib.load(f)

    raw_tabs = data.get("tabs")
    if not isinstance(raw_tabs, list) or not raw_tabs:
        raise click.ClickException("Config must define at least one [[tabs]] entry.")

    global_path: Path | None = None
    if "path" in data:
        global_path_raw = Path(str(data["path"])).expanduser()
        global_path = global_path_raw if global_path_raw.is_absolute() else (config_path.parent / global_path_raw).resolve()

    tabs: list[WorkspaceTab] = []
    for idx, raw_tab in enumerate(raw_tabs, start=1):
        if not isinstance(raw_tab, dict):
            raise click.ClickException(f"Tab {idx} must be a table.")
        name = str(raw_tab.get("name", f"tab{idx}"))
        command = raw_tab.get("command")
        if command is not None:
            command = str(command)
        tab_path_value = raw_tab.get("path")
        tab_path = _resolve_tab_path(
            str(tab_path_value) if tab_path_value is not None else None,
            global_path,
            config_path.parent,
        )
        tabs.append(WorkspaceTab(name=name, command=command, path=tab_path))

    focus_tab = int(data.get("focus_tab", 1))
    if focus_tab < 1 or focus_tab > len(tabs):
        raise click.ClickException(f"focus_tab must be between 1 and {len(tabs)}.")

    return WorkspaceConfig(focus_tab=focus_tab, tabs=tabs)


def render_applescript(config: WorkspaceConfig) -> str:
    # Focusing with AppleScript `select tab (tab N of win)` is unreliable for Ghostty workspaces:
    # Ghostty's ScriptTab.handleSelectTab currently brings the window forward but does not reliably
    # switch the active tab for scripted multi-tab startup. We therefore emit a Ghostty action:
    # `perform action "goto_tab:N"` on a terminal in the target window, which uses Ghostty's
    # tab-navigation path and consistently lands on the requested 1-based index from `focus_tab`.
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(APPLESCRIPT_TEMPLATE_NAME)
    tab_payload = [
        {
            "applescript_command": _build_tab_shell_command(tab),
            "applescript_title": _applescript_escape(tab.name),
        }
        for tab in config.tabs
    ]
    return template.render(tabs=tab_payload, focus_tab=config.focus_tab)


def run_workspace(config: WorkspaceConfig) -> None:
    script = render_applescript(config)
    subprocess.run(["osascript", "-e", script], check=True)


@click.command()
@click.argument("workspace_name", required=False)
@click.option("--config", "config_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
def main(workspace_name: str | None, config_path: Path | None) -> None:
    """Open a Ghostty workspace from TOML config."""
    config = load_workspace_config(workspace_name=workspace_name, config_path=config_path)
    run_workspace(config)


if __name__ == "__main__":
    main()
