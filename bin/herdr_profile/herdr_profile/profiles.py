"""Herdr app profiles: windows of their own with the main window's setup.

A profile <name> is the app home ~/.config/herdr-app-<name> plus the herdr-core session <name>, here
and on each machine. Spaces, tabs and terminals live in the session, so only the home and the
session's machines are set up here; removing a profile leaves its sessions and terminals running.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

PROFILE_NAME = re.compile(r"[A-Za-z0-9_-]+")


class ProfileError(Exception):
    pass


class Machine(TypedDict):
    """A machine entry of `herdr-core machine ls --json`."""

    name: str
    target: str
    # True when reached with a command (`--via`) rather than ssh.
    via: bool
    # The herdr-core session it reaches there; None is that machine's default session.
    session: str | None


@dataclass(frozen=True)
class Profile:
    name: str
    config_root: Path

    @property
    def home(self) -> Path:
        return self.config_root / f"herdr-app-{self.name}"


@dataclass(frozen=True)
class ProfileSources:
    # herdr-app/ in this repository: settings, keys, themes and our own mods, linked.
    repo_config: Path
    # ~/.config/herdr-app: third-party mods and the main-copy layout, copied.
    main_home: Path


def setup_profile(profile: Profile, sources: ProfileSources, *, local: bool = False) -> None:
    sync_profile_files(profile, sources)
    if not local:
        sync_profile_machines(profile)


def sync_profile_files(profile: Profile, sources: ProfileSources) -> None:
    main_layout = sources.main_home / "layouts/main-copy.json"
    if not main_layout.is_file():
        raise ProfileError(f"{main_layout} is missing; run `just herdr-app` first")
    home = profile.home
    for folder in ("mods", "themes", "layouts"):
        (home / folder).mkdir(parents=True, exist_ok=True)

    link_config(sources.repo_config / "settings.json", home / "settings.json")
    link_config(sources.repo_config / "keys.json", home / "keys.json")
    for theme in sorted((sources.repo_config / "themes").glob("*.json")):
        link_config(theme, home / "themes" / theme.name)
    for mod in sorted(path for path in (sources.repo_config / "mods").iterdir() if path.is_dir()):
        link_config(mod, home / "mods" / mod.name)

    # Third-party mods are copied: a linked mod loses its icons. In the main home they are the
    # mods that are neither our links nor Herdr's shipped mods (installed.json).
    shipped = json.loads((sources.main_home / "installed.json").read_text())
    for mod in sorted((sources.main_home / "mods").iterdir()):
        if mod.is_symlink() or not mod.is_dir() or mod.name in shipped:
            continue
        subprocess.run(["rsync", "-a", "--delete", f"{mod}/", f"{home / 'mods' / mod.name}/"], check=True)

    copy_profile_layout(main_layout, home / "layouts/main-copy.json")
    # The window's layout choice is kept in shared.json; a new profile starts on main-copy.
    shared = home / "shared.json"
    if not shared.exists():
        shared.write_text('{"layout": "main-copy"}\n')


def link_config(source: Path, link: Path) -> None:
    if link.exists() and not link.is_symlink():
        raise ProfileError(f"{link} exists and is not a link; move it first")
    link.unlink(missing_ok=True)
    link.symlink_to(source)


def copy_profile_layout(source: Path, destination: Path) -> None:
    """Copy a layout with its sidebar blocks hidden and empty.

    The sidebar writes the address of the terminal it shows into the layout, and in the main
    home's layout that terminal is in the main window's session.
    """
    layout = json.loads(source.read_text())
    _hide_sidebar(layout)
    partial = destination.with_name(destination.name + ".tmp")
    partial.write_text(json.dumps(layout, indent=2) + "\n")
    partial.replace(destination)


def _hide_sidebar(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("id") == "app-sidebar":
            node["content"] = {"mod": "app-sidebar"}
            node["hidden"] = True
        for child in node.values():
            _hide_sidebar(child)
    elif isinstance(node, list):
        for child in node:
            _hide_sidebar(child)


def sync_profile_machines(profile: Profile) -> None:
    """Give the profile's session the main session's ssh machines, each reaching its <name> session.

    A machine entry names the remote session it reaches (null: that machine's default, the main
    window's). One reaching another session is removed and added again, which only forgets it
    here and leaves its terminals running.
    """
    registered = {machine["name"]: machine for machine in list_machines(profile.name)}
    for machine in list_machines(None):
        if machine["via"]:
            continue
        current = registered.get(machine["name"])
        if current and current["session"] == profile.name:
            continue
        if current:
            _run_core(profile.name, "machine", "rm", machine["name"])
        _run_core(
            profile.name, "machine", "add", machine["target"], "--name", machine["name"], "--session", profile.name
        )
        print(f"profile {profile.name}: {machine['name']} reached in its {profile.name} session")


def list_machines(session: str | None) -> list[Machine]:
    """The machines of a local herdr-core session; None is the default session, the main window's."""
    result = subprocess.run(
        ["herdr-core", "machine", "ls", "--json"], env=_core_env(session), stdout=subprocess.PIPE, text=True, check=True
    )
    return json.loads(result.stdout)["machines"]


def _run_core(session: str, *args: str) -> None:
    subprocess.run(["herdr-core", *args], env=_core_env(session), stdout=subprocess.DEVNULL, check=True)


def _core_env(session: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("HC_SESSION", None)
    if session is not None:
        env["HC_SESSION"] = session
    return env


def discover_profiles(config_root: Path) -> list[Profile]:
    """The profiles with a home under config_root; homes not named like a profile (a backup) are left out."""
    profiles = []
    for home in sorted(config_root.glob("herdr-app-*")):
        name = home.name.removeprefix("herdr-app-")
        if home.is_dir() and PROFILE_NAME.fullmatch(name):
            profiles.append(Profile(name, config_root))
    return profiles


def open_profile(profile: Profile, sources: ProfileSources) -> None:
    """Open the profile's window, or bring it forward; a missing profile is set up first, with machines."""
    if not profile.home.exists():
        setup_profile(profile, sources)
    subprocess.run(
        [
            "open",
            "-n",
            "-a",
            "/Applications/Herdr.app",
            "--env",
            f"HERDR_APP_HOME={profile.home}",
            "--env",
            f"HC_SESSION={profile.name}",
        ],
        check=True,
    )


def remove_profile(profile: Profile) -> None:
    if profile.home.exists():
        shutil.rmtree(profile.home)
