# Drift checks and ongoing setup

- **Check for drift:** Run `principles list-member-problems --short`:
  - Exit `0`: all mapped members match their audited baseline.
  - Exit `1`: refusal (e.g., `broken_members` for a renamed/deleted file or section) — follow `repair` / `repair_with` on stderr.
  - Exit `3`: a member changed or has no completed audit — follow its printed commands (drop `--short` for full JSON `next_action`).
- **Open findings:** Run `principles list-open-findings`.
- **Meta-principle (`sticking-to-your-principles`):** Run `principles show-meta-principle-passage` and follow its `question` and `next_action` with the user before editing any entry file.
- **Hooks:** Run `principles show-hook-setup` and show the entries to the user before writing or merging them into settings.
