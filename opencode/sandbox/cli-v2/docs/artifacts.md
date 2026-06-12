# CLI v2 Artifacts

Every OpenCode-backed CLI v2 command writes artifacts under `<sandbox-root>/output`.

## Files

- `command.txt` records the OpenCode command line.
- `metadata.json` records command, agent, source paths, prompt source, and sandbox paths.
- `stdout.txt` captures OpenCode stdout.
- `stderr.txt` captures OpenCode stderr.
- `opencode-exit-status.txt` records the raw OpenCode status or CLI substitute status.
- `exit-status.txt` records the final CLI status.

## Status Values

- `0` means OpenCode completed successfully.
- Any other OpenCode status is returned as-is for normal runs.
- `127` means the OpenCode executable was not found.
- `124` means the CLI timeout stopped the run.
- `1` means setup or usage failed.
