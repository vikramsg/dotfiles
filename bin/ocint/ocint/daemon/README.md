# ocint Daemon Package

```text
daemon package -> concise index -> focused references -> lch operations
```

The daemon package contains two application processes over one durable database.
The bounded timer process polls GitHub, runs repository work through OpenCode,
validates it, and owns commit, SSH push, and pull-request publication. The
always-on coordinator process accepts signed Slack Events, runs a restricted
OpenCode conversation in a generated context workspace, and replies only in the
originating Slack thread.

```text
GitHub poll -> task/job repository --------\
                                           -> daemon.sqlite + one migration chain
Slack event -> coordinator repository -----/
```

Each domain repository owns its transitions. Shared `db/` code owns physical
schema, WAL/foreign-key/busy-timeout policy, and serialized migrations.

Documentation:

- [Daemon documentation index](../../docs/daemon.md)
- [Minimal pull-request workflow](../../docs/daemon/workflow.md)
- [Operations and job inspection](../../docs/daemon/operations.md)
- [Architecture](../../docs/daemon/architecture/architecture.md)
- [Security and attach authentication](../../docs/daemon/security.md)
- [systemd lifecycle surface](lch/README.md)

`pull_request_job/` owns the durable GitHub execution workflow.
`coordinator/` owns normalized conversations, turns, delivery state, workspace,
and recovery. `slack/` owns Events/Web API protocol details. `git/` and
`opencode/` remain independent sibling adapters, and `cli.py` composes both
processes through narrow facades.

The package intentionally contains no distributed coordinator worker protocol,
generic lifecycle framework, or compatibility credential fallback. Phase 1 has
one coordinator runtime lock and no repository execution route from Slack.
`lch/` owns the concrete Linux user-systemd implementation.
