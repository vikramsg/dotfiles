# ocint Releases

Every ocint change, including a release, goes through a pull request. Do not commit or push directly
to `main`. The process creates annotated Git tags but no GitHub Releases.

## Version and notes

ocint uses stable Semantic Versioning (`X.Y.Z`) without prerelease or build metadata. During `0.x`,
use a patch increment for compatible fixes and a minor increment for new behavior.
`bin/ocint/pyproject.toml` is authoritative; `uv.lock` records the same version.

The changelog contains UTC-dated, subject-only entries from `ocint: ` squash-merge subjects after
the previous annotated `ocint-v*` tag. Other scopes are omitted and malformed ocint subjects fail.

## Prepare and open the PR

Fetch current history, then create the exact release branch from locally known `origin/main`:

```sh
git fetch origin main --tags
git switch -c ocint-release/vX.Y.Z origin/main
just ocint-release-prepare X.Y.Z
```

Preparation requires branch HEAD to equal `origin/main`. It updates exactly:

- `bin/ocint/pyproject.toml`
- `bin/ocint/CHANGELOG.md`
- `uv.lock`

It runs lock, package test, check, and smoke verification and restores all three paths on failure.
It never commits, tags, pushes, or installs. A valid prepared rerun is idempotent.

Review the files, commit and push the release branch through the normal development process, and
open a PR titled exactly `ocint: Release vX.Y.Z`. Required CI must include the normal **Validate PR
title** check and **Release validation**. The latter is not applicable and succeeds for ordinary
PRs; any release-file change requires all three files and the exact release branch and title.

Squash-merge the approved release PR. The resulting main subject may include GitHub's ` (#123)`
suffix. The main-push workflow validates the squash commit against its first parent and creates and
pushes only annotated tag `ocint-vX.Y.Z`. It does not push a branch, install ocint, or create a
GitHub Release.

After CI succeeds, update and install locally:

```sh
git pull --ff-only
git fetch --tags
just ocint
ocint --version
```

If tag validation fails, fix the release state only through another PR. Never repair main or a tag
with a direct commit, branch push, force-push, or local release command.

## Historical baseline

Commit `8e13c509ec1b31a6f97501ef3f0215a4bdb58a8e` is the historical baseline because it introduced
`bin/ocint/pyproject.toml` with package version `0.1.0`. To create `ocint-v0.1.0` once, run the
**ocint release** workflow manually on `main` and enter the exact baseline confirmation requested
by `workflow_dispatch`. The guarded CI operation verifies that commit and version before pushing an
annotated tag. Conflicting tags fail; an existing annotated tag on that commit is idempotent.
