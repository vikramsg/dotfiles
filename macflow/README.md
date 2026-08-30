# macflow configuration

This directory contains the repo-managed configuration for the `macflow` tool.

## Source of truth

```text
repo: macflow/config.json
live: ${XDG_CONFIG_HOME:-~/.config}/macflow/config.json
```

Run `just macflow` to link the configuration and delegate build and installation
to `bin/macflow/justfile`.

The screenshot directory itself continues to come from the existing
`${XDG_CONFIG_HOME:-~/.config}/screenshot/config.json` file.
