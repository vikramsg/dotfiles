# Hunk

Hunk opens in a Herdr popup with a review flow modeled after the Neovim
CodeDiff setup.

## Setup

```sh
just hunk
```

This installs the `hunk-review` launcher and links the configuration and
extensions into `~/.config/hunk`. Do not run the recipe when testing an
uninstalled change; use a temporary `XDG_CONFIG_HOME` and invoke the launcher
from `bin/hunk-review/hunk-review` instead.

## Review selection

`hunk-review` starts with uncommitted changes when the working tree is dirty.
When it is clean, it reviews changes since the branch split from `main`. It
exits with a message when neither review contains changes.

## Keys

| Key | Action |
| --- | --- |
| `B` | Toggle between the working tree and `main...HEAD` |
| `Ctrl+B` | Choose another review target |
| `t` | Toggle stacked and side-by-side layouts |
| `S` | Save current review comments and continue reviewing |
| `[` / `]` | Previous / next hunk |
| `,` / `.` | Previous / next file |
| `e` | Open the selected file in `$EDITOR` |
| `a` | Toggle agent comments |
| `?` | Show Hunk help |
| `q` | Quit Hunk |

## Saved reviews

`S` exports Hunk's current saved human and live-agent comments without closing
or reloading the review. The default output is:

```text
.agents/reviews/hunk-review.json
```

The directory must be ignored by Git so writing the export cannot change the
diff being reviewed. Change the repository-relative path in the user config:

```toml
[extension.review-workflow]
review_path = ".agents/reviews/hunk-review.json"
```

The configured file must stay under `.agents/reviews/` and be ignored by Git.
Absolute paths, path or symlink escapes, and non-ignored files are refused. The
output is Hunk's review snapshot format for agents or other tools to consume;
it is not an `--agent-context` input file.
