# gh-stats

Summarize pull requests merged by a GitHub user across repositories visible to the authenticated `gh` CLI.

## Install

```bash
just gh-stats
```

Authenticate first with `gh auth login`. The default report covers 10 Monday-aligned weeks.

## Usage

```bash
gh-stats
gh-stats --weeks 52
gh-stats --weeks 52 --per-repo
```

The default table shows weekly totals across all repositories. `--per-repo` adds an explicit repository column and only shows week/repository rows containing merged pull requests.

Use `gh-stats --help` for command help. Large GitHub searches are split into bounded date ranges to avoid the 1,000-result search cap.
