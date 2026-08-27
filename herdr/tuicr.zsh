#!/usr/bin/env zsh

: <<'DOC'
Is this a GitHub repository?
        │
        ├── No
        │   └── Open tuicr's normal selector
        │
        └── Yes
            │
            ├── Current branch has an OPEN PR
            │   └── Open tuicr directly with that PR URL
            │
            └── No open PR
                └── Open tuicr's normal selector
DOC

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    pr_url=$(gh pr view --json state,url --jq 'select(.state == "OPEN") | .url' 2>/dev/null)
    if [[ -n "$pr_url" ]]; then
        exec tuicr pr "$pr_url" --no-update-check
    fi
fi

exec tuicr --no-update-check
