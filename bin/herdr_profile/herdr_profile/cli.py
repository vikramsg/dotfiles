import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from herdr_profile import profiles
from herdr_profile.profiles import Profile, ProfileError, ProfileSources

# Installed editable (bin/herdr_profile/justfile), so this file stays in the repository.
REPO = Path(__file__).resolve().parents[3]

app = typer.Typer(
    no_args_is_help=True,
    help="Herdr app profiles: windows whose spaces, tabs and terminals are apart from the main window's.",
)


def _profile_name(name: str) -> str:
    if not profiles.PROFILE_NAME.fullmatch(name):
        raise typer.BadParameter("use letters, digits, - and _")
    return name


Name = Annotated[
    str, typer.Argument(callback=_profile_name, help="Profile name, also its herdr-core session here and on the VM.")
]


def _config_root() -> Path:
    return Path.home() / ".config"


def _sources() -> ProfileSources:
    return ProfileSources(repo_config=REPO / "herdr-app", main_home=_config_root() / "herdr-app")


@app.command()
def setup(
    name: Name,
    local: Annotated[bool, typer.Option("--local", help="Leave out the main window's machines on this run.")] = False,
) -> None:
    """Set up or refresh a profile's home from the main window's setup."""
    profiles.setup_profile(Profile(name, _config_root()), _sources(), local=local)
    print(f"profile {name}: set up")


@app.command("open")
def open_(name: Name) -> None:
    """Open a profile's window, or bring it forward; a missing profile is set up first, with machines."""
    profiles.open_profile(Profile(name, _config_root()), _sources())


@app.command("list")
def list_() -> None:
    """Show the profiles, the ones `refresh` sets up again."""
    for profile in profiles.discover_profiles(_config_root()):
        print(profile.name)


@app.command()
def refresh() -> None:
    """Set up every profile again, with machines, after the main window's setup changed."""
    for profile in profiles.discover_profiles(_config_root()):
        profiles.setup_profile(profile, _sources())
        print(f"profile {profile.name}: set up")


@app.command()
def remove(name: Name) -> None:
    """Delete a profile's home; close its window first. Its terminals keep running in its herdr-core session."""
    profiles.remove_profile(Profile(name, _config_root()))
    print(f"profile {name}: removed")


def main() -> None:
    try:
        app()
    except (ProfileError, subprocess.CalledProcessError) as error:
        sys.exit(f"herdr-profile: {error}")
