import sys
from pathlib import Path

import pytest
from pydantic_ai_pax.config.builtins import DEFAULT_PLUGINS
from pydantic_ai_pax.config.settings_store import SettingsStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configure  # noqa: E402

MODEL = 'openai-codex:gpt-6.2-sol'


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    return SettingsStore()


def saved(store):
    return {plugin.id: plugin for plugin in store.plugins()}


def test_disables_builtins_and_leaves_others_alone(store):
    assert configure.main(['--disable', 'herdr', 'notifications']) == 0

    plugins = saved(store)
    assert not plugins['herdr'].enabled
    assert not plugins['notifications'].enabled
    assert set(plugins) == {'herdr', 'notifications'}


def test_keeps_settings_saved_for_the_plugin(store):
    shipped = next(plugin for plugin in DEFAULT_PLUGINS if plugin.id == 'notifications')
    store.save_plugin(shipped.model_copy(update={'settings': {'sound': False}}))

    configure.main(['--disable', 'notifications'])

    plugin = saved(store)['notifications']
    assert not plugin.enabled
    assert plugin.settings == {'sound': False}


def test_running_again_changes_nothing(store, capsys):
    args = ['--disable', 'herdr', '--effort', MODEL, 'high']
    configure.main(args)
    before = (saved(store), store.model_settings(MODEL))

    configure.main(args)

    assert (saved(store), store.model_settings(MODEL)) == before
    out = capsys.readouterr().out
    assert 'already disabled' in out
    assert 'effort already high' in out


def test_sets_effort_and_keeps_other_model_settings(store):
    store.save_model_settings(MODEL, {'openai_reasoning_effort': 'medium', 'max_tokens': 4000})

    assert configure.main(['--effort', MODEL, 'high']) == 0

    assert store.model_settings(MODEL) == {'openai_reasoning_effort': 'high', 'max_tokens': 4000}


@pytest.mark.parametrize(
    'args',
    [
        ['--disable', 'herdr', 'no-such-plugin'],
        ['--disable', 'herdr', '--effort', MODEL, 'extreme'],
    ],
)
def test_bad_input_fails_without_saving(store, args):
    assert configure.main(args) == 1
    assert saved(store) == {}
    assert store.model_settings(MODEL) == {}
