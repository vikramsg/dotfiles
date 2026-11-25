"""Apply this repository's Pax settings: built-in plugins to turn off and a model's reasoning effort.

Pax keeps both only in its settings database, and its CLI cannot change them, so this
saves what `/plugins disable NAME` and `/effort VALUE` save, through Pax's own settings
store. Run it with the interpreter of the installed Pax (see the justfile), so it writes
the schema that Pax version reads. It has no uv script header: inline metadata would make
uv build a separate environment without Pax in it.
"""

import argparse
import sys

from pydantic_ai_pax.config.builtins import DEFAULT_PLUGINS
from pydantic_ai_pax.config.settings_store import SettingsStore
from pydantic_ai_pax.models.model_settings import ModelSettingsForm

EFFORT = 'openai_reasoning_effort'


def disable_plugins(store: SettingsStore, names: list[str]) -> None:
    builtins = {plugin.id: plugin for plugin in DEFAULT_PLUGINS}
    saved = {plugin.id: plugin for plugin in store.plugins()}
    for name in names:
        # Keep settings someone saved for it; otherwise start from what Pax ships.
        current = saved.get(name, builtins[name])
        if not current.enabled:
            print(f'{name}: already disabled')
            continue
        store.save_plugin(current.model_copy(update={'enabled': False}))
        print(f'{name}: disabled')


def set_effort(store: SettingsStore, model: str, effort: str) -> None:
    settings = store.model_settings(model)
    if settings.get(EFFORT) == effort:
        print(f'{model}: effort already {effort}')
        return
    # Keep the model's other saved settings.
    store.save_model_settings(model, {**settings, EFFORT: effort})
    print(f'{model}: effort {effort}')


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--disable', nargs='+', default=[], metavar='PLUGIN', help="built-in plugins to turn off")
    parser.add_argument('--effort', nargs=2, metavar=('MODEL', 'EFFORT'), help="a model's reasoning effort")
    args = parser.parse_args(argv)

    builtins = {plugin.id for plugin in DEFAULT_PLUGINS}
    unknown = [name for name in args.disable if name not in builtins]
    if unknown:
        print(f'Not built-in Pax plugins: {", ".join(unknown)}', file=sys.stderr)
        return 1
    if args.effort:
        try:
            ModelSettingsForm.model_validate({EFFORT: args.effort[1]})
        except ValueError:
            print(f'Not a reasoning effort: {args.effort[1]}', file=sys.stderr)
            return 1

    store = SettingsStore()
    disable_plugins(store, args.disable)
    if args.effort:
        set_effort(store, *args.effort)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
