"""Turn off Pax's built-in plugins by name, as `/plugins disable NAME` does in a session.

Pax keeps plugin choices only in its settings database and its CLI cannot change them,
so this saves the same disabled declaration through Pax's own settings store. Run it
with the interpreter of the installed Pax (see the justfile), so it writes the schema
that Pax version reads.
"""

import sys

from pydantic_ai_pax.config.builtins import DEFAULT_PLUGINS
from pydantic_ai_pax.config.settings_store import SettingsStore


def main(names: list[str]) -> int:
    builtins = {plugin.id: plugin for plugin in DEFAULT_PLUGINS}
    unknown = [name for name in names if name not in builtins]
    if unknown:
        print(f'Not built-in Pax plugins: {", ".join(unknown)}', file=sys.stderr)
        return 1
    store = SettingsStore()
    saved = {plugin.id: plugin for plugin in store.plugins()}
    for name in names:
        # Keep settings someone saved for it; otherwise start from what Pax ships.
        current = saved.get(name, builtins[name])
        if not current.enabled:
            print(f'{name}: already disabled')
            continue
        store.save_plugin(current.model_copy(update={'enabled': False}))
        print(f'{name}: disabled')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
