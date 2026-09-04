# hunk-review launcher

`hunk-review` selects the same initial comparison as the Neovim CodeDiff
workflow before handing terminal ownership to Hunk:

- a dirty working tree opens `hunk diff`;
- a clean feature branch opens `hunk diff main...`;
- a clean branch with no changes exits with a short message.

The launcher exports `HUNK_REVIEW_TARGET` so the Hunk review-workflow extension
can make its first `B` toggle deterministic.

Run the behavioral tests with:

```sh
just --justfile bin/hunk-review/justfile test
```
