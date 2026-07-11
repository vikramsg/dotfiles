# ocint releases

Prepare with `just ocint-release-prepare X.Y.Z`, review the three changed files, then run
`just ocint-release-publish X.Y.Z` (or add `--yes`). Publishing creates only a local commit,
annotated tag, and tool installation. It never pushes or creates a GitHub release.

The one-time historical baseline tag is intentionally manual and must not be created as part
of bootstrap or normal preparation:

```sh
git tag -a ocint-v0.1.0 8e13c509ec1b31a6f97501ef3f0215a4bdb58a8e -m "ocint v0.1.0"
```
