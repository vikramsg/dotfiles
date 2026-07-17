# ocint Roadmap

```text
typed configuration -> generated units -> managed lifecycle
```

## Future systemd lifecycle

Follow the lch operational model in a future change: generate units from typed
configuration, install them, run `daemon-reload` and enable/start, expose status
and `journalctl` logs, and support a complete disable/uninstall flow.

Unlike lch user units, production daemon and OpenCode units must use separate
system-level identities. OpenCode execution credentials and daemon publication
credentials must remain isolated. No systemd files or lifecycle commands are
implemented by the current MVP.
