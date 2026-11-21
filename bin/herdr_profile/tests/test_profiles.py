import json

import pytest
from typer.testing import CliRunner

from herdr_profile.cli import app
from herdr_profile.profiles import (
    Profile,
    ProfileError,
    ProfileSources,
    copy_profile_layout,
    discover_profiles,
    remove_profile,
    setup_profile,
)

LAYOUT = {
    "id": "root",
    "children": [
        {"id": "app-sidebar", "content": {"mod": "app-sidebar", "terminal": "t7"}},
        {"id": "files", "content": {"mod": "filetree"}},
    ],
}


@pytest.fixture
def sources(tmp_path):
    repo = tmp_path / "repo/herdr-app"
    (repo / "themes").mkdir(parents=True)
    (repo / "mods/own").mkdir(parents=True)
    (repo / "settings.json").write_text("{}")
    (repo / "keys.json").write_text("{}")
    (repo / "themes/dark.json").write_text("{}")

    main = tmp_path / "config/herdr-app"
    (main / "layouts").mkdir(parents=True)
    (main / "layouts/main-copy.json").write_text(json.dumps(LAYOUT))
    (main / "installed.json").write_text(json.dumps({"shipped": {}}))
    (main / "mods/shipped").mkdir(parents=True)
    (main / "mods/gitview/icons").mkdir(parents=True)
    (main / "mods/gitview/icons/branch.svg").write_text("<svg/>")
    (main / "mods/own").symlink_to(repo / "mods/own")
    return ProfileSources(repo_config=repo, main_home=main)


@pytest.fixture
def work(tmp_path):
    return Profile("work", tmp_path / "config")


def test_local_setup_links_repo_config_and_copies_only_third_party_mods(sources, work):
    setup_profile(work, sources, local=True)

    assert (work.home / "settings.json").resolve() == sources.repo_config / "settings.json"
    assert (work.home / "themes/dark.json").resolve() == sources.repo_config / "themes/dark.json"
    assert (work.home / "mods/own").resolve() == sources.repo_config / "mods/own"
    copied = work.home / "mods/gitview"
    assert not copied.is_symlink()
    assert (copied / "icons/branch.svg").read_text() == "<svg/>"
    assert not (work.home / "mods/shipped").exists()


def test_setup_again_mirrors_changed_and_deleted_mod_files(sources, work):
    setup_profile(work, sources, local=True)
    mod = sources.main_home / "mods/gitview"
    (mod / "icons/branch.svg").unlink()
    (mod / "init.lua").write_text("v2")

    setup_profile(work, sources, local=True)

    assert not (work.home / "mods/gitview/icons/branch.svg").exists()
    assert (work.home / "mods/gitview/init.lua").read_text() == "v2"


def test_setup_keeps_the_profiles_own_state(sources, work):
    setup_profile(work, sources, local=True)
    (work.home / "shared.json").write_text('{"layout": "main"}')
    (work.home / "window.json").write_text('{"x": 10}')

    setup_profile(work, sources, local=True)

    assert (work.home / "shared.json").read_text() == '{"layout": "main"}'
    assert (work.home / "window.json").read_text() == '{"x": 10}'


def test_new_profile_starts_on_main_copy(sources, work):
    setup_profile(work, sources, local=True)

    assert json.loads((work.home / "shared.json").read_text()) == {"layout": "main-copy"}


def test_setup_refuses_to_replace_a_file_with_a_link(sources, work):
    (work.home).mkdir(parents=True)
    (work.home / "settings.json").write_text('{"mine": true}')

    with pytest.raises(ProfileError):
        setup_profile(work, sources, local=True)

    assert (work.home / "settings.json").read_text() == '{"mine": true}'


def test_layout_copy_drops_the_sidebar_terminal_and_keeps_the_rest(tmp_path):
    source = tmp_path / "main-copy.json"
    source.write_text(json.dumps(LAYOUT))
    destination = tmp_path / "copy.json"

    copy_profile_layout(source, destination)

    sidebar, files = json.loads(destination.read_text())["children"]
    assert sidebar == {"id": "app-sidebar", "content": {"mod": "app-sidebar"}, "hidden": True}
    assert files == LAYOUT["children"][1]
    assert json.loads(source.read_text()) == LAYOUT


def test_discover_profiles_leaves_out_homes_not_named_like_a_profile(tmp_path):
    config = tmp_path / "config"
    for folder in ("herdr-app", "herdr-app-work", "herdr-app-agent_test", "herdr-app-old.bak"):
        (config / folder).mkdir(parents=True)
    (config / "herdr-app-notes").write_text("")

    assert [profile.name for profile in discover_profiles(config)] == ["agent_test", "work"]


def test_remove_deletes_only_that_profiles_home(sources, work, tmp_path):
    other = Profile("other", work.config_root)
    setup_profile(work, sources, local=True)
    setup_profile(other, sources, local=True)

    remove_profile(work)

    assert not work.home.exists()
    assert other.home.is_dir()
    assert (sources.repo_config / "settings.json").is_file()
    assert (sources.main_home / "mods/gitview/icons/branch.svg").is_file()


def test_cli_rejects_names_outside_letters_digits_dash_and_underscore(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".config/herdr-app").mkdir(parents=True)

    for args in (["remove", "../herdr-app"], ["setup", "a b", "--local"], ["setup", "work", "--remote"]):
        assert CliRunner().invoke(app, args).exit_code != 0

    assert (tmp_path / ".config/herdr-app").is_dir()
    assert sorted(p.name for p in (tmp_path / ".config").iterdir()) == ["herdr-app"]
