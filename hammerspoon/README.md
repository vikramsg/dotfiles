# Hammerspoon

## Debugging

When a hotkey is registered but appears to do nothing, invoke its exact callback
through the Hammerspoon CLI before inspecting application or window state:

```bash
hs -c 'FlowVisionShelfInstance:show()'
```

This returns callback stack traces directly. Hammerspoon otherwise catches
hotkey callback exceptions and writes them to its Console, so the hotkey can
still appear enabled while its callback fails.

After fixing the callback, reload the configuration and run its unit tests:

```bash
hs -c 'hs.reload()'
just --justfile hammerspoon/justfile test
```

The reload command may report a message-port invalidation because Hammerspoon
disconnects the CLI while reloading; verify the loaded hotkey afterward:

```bash
hs -c 'return hs.inspect(hs.hotkey.getHotkeys())'
```
