# Daemon bootstrap acceptance

`daemon-bootstrap: pending`

The parent process performs this acceptance after the implementation PR is
available. Do not run it from automated tests.

1. Start `opencode serve` with `OPENCODE_CONFIG` pointing at
   `bin/ocint/config/opencode.daemon.json` and a server password.
2. Set `OCINT_DAEMON_CONFIG`, `OCINT_DAEMON_API_TOKEN`,
   `OCINT_DAEMON_OPENCODE_PASSWORD`, and `OCINT_DAEMON_GITHUB_TOKEN`.
3. Run `ocint daemon migrate`, then `ocint daemon run` in the foreground.
4. Submit the deterministic documentation request with
   `ocint daemon submit dotfiles "Add the agreed daemon bootstrap acceptance marker only." --idempotency-key daemon-bootstrap-v1`.
5. Follow it with `ocint daemon status`. The control service—not OpenCode—must
   validate, commit, push, and idempotently publish the real pull request.

The execution service must not receive GitHub credentials. The bootstrap may
use the control process's existing GitHub authentication only when explicitly
supplied by the parent.
