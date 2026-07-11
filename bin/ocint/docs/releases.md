# ocint Releases

The repository maintainer owns ocint releases. Release automation prepares and publishes local
Git state, but it never pushes commits or tags and never creates a GitHub release.

## Versioning

ocint uses stable Semantic Versioning in `X.Y.Z` form. While the CLI contract is evolving under
`0.x`:

- Increment the patch version for compatible fixes.
- Increment the minor version for new commands, options, output, or behavior.
- Do not use prerelease or build metadata.

`bin/ocint/pyproject.toml` is the authoritative version source. `uv.lock` records the same package
version, and `ocint --version` reads installed package metadata.

## Release Notes

Release notes come from squash-merge commit subjects beginning with `ocint: ` after the previous
`ocint-v*` tag. The release tool removes that prefix, preserves the pull request number, and writes
subject-only entries under a UTC-dated heading in `bin/ocint/CHANGELOG.md`.

Pull request titles therefore need to describe the user-visible result. Commits with other scopes
are excluded, malformed `ocint` prefixes fail preparation, and an empty ocint release range is not
releasable.

## Preconditions

Run releases from the repository root. Before preparing a release:

- Check out `main`.
- Fetch manually so the locally known `origin/main` is current.
- Ensure local `main` exactly matches `origin/main`.
- Ensure the worktree is clean.
- Ensure the previous `ocint-v*` tag is annotated and matches the package version at its commit.
- Choose a stable version greater than the current package version.

## Historical Baseline

The existing `0.1.0` package predates release automation. Create its baseline tag once, manually,
after confirming the historical commit contains version `0.1.0`:

```sh
git show 8e13c509ec1b31a6f97501ef3f0215a4bdb58a8e:bin/ocint/pyproject.toml
git tag -a ocint-v0.1.0 8e13c509ec1b31a6f97501ef3f0215a4bdb58a8e -m "ocint v0.1.0"
git cat-file -t ocint-v0.1.0
git rev-parse ocint-v0.1.0^{}
```

The release script does not create this historical tag.

## Prepare

Prepare the next version:

```sh
just ocint-release-prepare X.Y.Z
```

Preparation validates the repository, version, tag history, and release commits. It then updates
exactly these files:

- `bin/ocint/pyproject.toml`
- `bin/ocint/CHANGELOG.md`
- `uv.lock`

It runs the lock check and the package test, static-check, and smoke recipes. If validation fails
after mutation, it restores all three files. It does not commit, tag, install, or push.

Review the generated changes before publishing:

```sh
git status --short
git diff -- bin/ocint/pyproject.toml bin/ocint/CHANGELOG.md uv.lock
```

Running prepare again for the same valid state is safe and reports that the release is already
prepared.

## Publish

Publish the reviewed local release:

```sh
just ocint-release-publish X.Y.Z
```

Publishing revalidates the three prepared files and reruns all release checks before asking for
confirmation. It then:

1. Creates commit `ocint: Release vX.Y.Z` containing exactly the three release files.
2. Creates annotated tag `ocint-vX.Y.Z` on that commit.
3. Reinstalls ocint with `uv tool install`.
4. Verifies the installed `ocint --version` output.

Use `--yes` only for trusted non-interactive execution:

```sh
just ocint-release-publish X.Y.Z --yes
```

Publish does not push the release commit or tag.

## Recovery

Publishing can be rerun safely after interruption. It recognizes a valid release commit without a
tag and a valid commit and tag without a completed installation. It resumes from that state rather
than creating duplicate commits or tags. Conflicting tags, unexpected files, altered changelog
content, or unrelated worktree changes stop the release.

## Verification

After publishing, verify the local release:

```sh
git show --stat --decorate HEAD
git cat-file -t ocint-vX.Y.Z
git rev-parse ocint-vX.Y.Z^{}
ocint --version
git status --short
```

Pushing a release tag, if ever desired, is a separate manual operation outside this process.
