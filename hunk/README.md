# Hunk

Hunk opens in a Herdr popup with a review flow modeled after the Neovim
CodeDiff setup.

## Setup

```sh
just zsh
just hunk
```

These recipes link the `hunk` shell function, configuration, and extensions.

## Review selection

Running `hunk` without arguments starts with uncommitted changes when the working
tree is dirty. When it is clean, it reviews changes since the branch split from
`main`. It exits with a message when neither review contains changes. Arguments
and subcommands are delegated to the native Hunk executable.

## Keys

| Key | Action |
| --- | --- |
| `B` | Toggle between the working tree and `main...HEAD` |
| `Ctrl+B` | Choose another review target |
| `t` | Toggle stacked and side-by-side layouts |
| `[` / `]` | Previous / next hunk |
| `,` / `.` | Previous / next file |
| `e` | Open the selected file in `$EDITOR` |
| `a` | Toggle agent comments |
| `?` | Show Hunk help |
| `q` | Quit Hunk |

## Saved reviews

Saving a human comment with `Ctrl+S`, or adding, updating, or removing an agent
comment, automatically exports Hunk's current saved comments without closing or
reloading the review. Draft comments are not exported. The default output is:

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
output is Hunk's live session review JSON for agents or other tools to consume;
it is not an `--agent-context` input file.
