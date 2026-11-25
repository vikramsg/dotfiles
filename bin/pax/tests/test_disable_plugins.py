import sys
from pathlib import Path

import pytest
from pydantic_ai_pax.config.builtins import DEFAULT_PLUGINS
from pydantic_ai_pax.config.settings_store import SettingsStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import disable_plugins  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    return SettingsStore()


def saved(store):
    return {plugin.id: plugin for plugin in store.plugins()}


def test_disables_builtins_and_leaves_others_alone(store):
    assert disable_plugins.main(['herdr', 'notifications']) == 0

    plugins = saved(store)
    assert not plugins['herdr'].enabled
    assert not plugins['notifications'].enabled
    assert set(plugins) == {'herdr', 'notifications'}


def test_keeps_settings_saved_for_the_plugin(store):
    shipped = next(plugin for plugin in DEFAULT_PLUGINS if plugin.id == 'notifications')
    store.save_plugin(shipped.model_copy(update={'settings': {'sound': False}}))

    disable_plugins.main(['notifications'])

    plugin = saved(store)['notifications']
    assert not plugin.enabled
    assert plugin.settings == {'sound': False}


def test_running_again_changes_nothing(store, capsys):
    disable_plugins.main(['herdr'])
    before = saved(store)

    disable_plugins.main(['herdr'])

    assert saved(store) == before
    assert 'already disabled' in capsys.readouterr().out


def test_unknown_name_fails_without_saving(store):
    assert disable_plugins.main(['herdr', 'no-such-plugin']) == 1
    assert saved(store) == {}
