# Daemon Pull Request Workflow

```text
operator
   |
   | start restricted OpenCode server
   v
opencode serve
   ^
   | HTTP + SSE, scoped to managed worktree
   |
operator ---> ocint daemon submit ---> authenticated control API
                                      |
                                      | persist before acceptance
                                      v
                                control SQLite DB
                                      |
                                      | atomic capacity lease
                                      v
                                  scheduler
                                      |
                         +------------+-------------+
                         |                          |
                         v                          v
                managed Git mirror          OpenCode session
                         |                          |
                         v                          | edit files only
                isolated worktree <----------------+
                         |
                         | configured validation
                         v
                control service commit
                         |
                         | control-only SSH credentials
                         v
                    git push branch
                         |
                         | control-only GitHub token
                         v
              find existing PR or create PR
                         |
                         v
              persist artifacts and completion
```

The control service owns orchestration, validation, Git publication, and pull
request creation. OpenCode receives a prompt and an isolated worktree, but it
does not receive GitHub tokens, SSH credentials, or permission to commit or
push.

Authentication details are documented separately:

- [GitHub REST authentication](auth/github.md)
- [Git push authentication](auth/git-push.md)
- [OpenCode server authentication](auth/opencode.md)
- [Control API authentication](auth/control-api.md)

## 1. Start OpenCode

Start one shared OpenCode server with the restricted daemon configuration and a
generated server password:

```bash
OPENCODE_CONFIG=/path/to/opencode.json \
OPENCODE_DISABLE_PROJECT_CONFIG=1 \
OPENCODE_SERVER_USERNAME=opencode \
OPENCODE_SERVER_PASSWORD="<generated-password>" \
opencode serve --pure --hostname 127.0.0.1 --port 4097
```

The policy permits file operations in the managed worktree root and denies
shell commands, web access, and access outside the configured root. Publication
credentials must not be present in this process environment.

Confirm the server version and health before starting the control service:

```bash
curl --fail --user "opencode:<generated-password>" \
  http://127.0.0.1:4097/global/health
```

## 2. Start The Control Service

Create the independent control database, then run the daemon:

```bash
OCINT_DAEMON_CONFIG=/path/to/daemon.toml \
uv run --package ocint --frozen ocint daemon migrate

OCINT_DAEMON_CONFIG=/path/to/daemon.toml \
CREDENTIALS_DIRECTORY=/path/to/control-credentials \
uv run --package ocint --frozen ocint daemon run
```

The credential directory supplies the daemon API token, OpenCode password, and
GitHub token. Git push uses the control process's explicit Git configuration,
credential file, or SSH agent. These values are excluded from OpenCode and
validation subprocess environments.

The daemon verifies OpenCode health before exposing a ready control API.

## 3. Submit Work

Submit a deterministic request with a stable idempotency key:

```bash
OCINT_DAEMON_CONFIG=/path/to/daemon.toml \
OCINT_DAEMON_API_TOKEN="<control-api-token>" \
uv run --package ocint --frozen ocint daemon submit dotfiles \
  "Create bin/ocint/DAEMON_ACCEPTANCE.md containing exactly one line: daemon-bootstrap: accepted. Do not modify any other file. Use file editing tools only and do not run shell commands." \
  --actor vikram_orbio_earth \
  --idempotency-key daemon-bootstrap-v1
```

The CLI sends an authenticated `POST /api/jobs` request. The control service
authorizes the actor and repository, deduplicates the idempotency key, and
persists the source event and queued job before returning `202 Accepted`.

## 4. Claim And Provision The Job

The scheduler atomically claims the queued job only when a durable execution
slot is available. It then provisions the repository without asking OpenCode to
clone anything.

For a new managed repository, the Git operations are equivalent to:

```bash
git clone --mirror \
  git@github.com:vikramsg/dotfiles.git \
  /control-root/mirrors/dotfiles.git

git -C /control-root/mirrors/dotfiles.git \
  worktree add /worktree-root/<job-id> \
  -b ocint/<job-id> <origin-main-revision>
```

The branch and worktree are recorded in the control database. The bootstrap
repository is based on clean `origin/main`, even when the daemon executable is
running from an implementation branch.

## 5. Run OpenCode

The daemon creates an OpenCode session through the HTTP API and sends the raw
resolved worktree path in `x-opencode-directory`. It submits the prompt and
monitors global and session events until the session becomes idle.

OpenCode edits files inside the assigned worktree. The daemon records the
session ID, server URL, worktree, and attach command so an operator can inspect
the same session:

```bash
opencode attach http://127.0.0.1:4097 \
  --dir /worktree-root/<job-id> \
  --session <session-id>
```

## 6. Validate The Result

The control service runs the repository's configured validation commands in a
credential-free environment. The bootstrap validator requires:

- Exactly one changed file.
- The file path to be `bin/ocint/DAEMON_ACCEPTANCE.md`.
- The file to contain exactly `daemon-bootstrap: accepted`.

Any validation failure stops the workflow before commit, push, or pull request
creation.

## 7. Commit And Push

After validation succeeds, the control service performs the publication steps.
OpenCode does not run them.

The commit operations are equivalent to:

```bash
git add --all
git commit --no-verify -m "ocint: complete job <job-id>"
```

The control service then pushes through the configured SSH remote using only
its publication environment:

```bash
git push --no-verify --set-upstream origin ocint/<job-id>
```

The commit SHA and push checkpoint are persisted so recovery does not create a
second commit or repeat a completed publication stage unnecessarily.

## 8. Find Or Create The Pull Request

Before creating a pull request, the daemon queries GitHub for an existing open
pull request with the same head and base:

```http
GET /repos/vikramsg/dotfiles/pulls
    ?state=open
    &head=vikramsg:ocint/<job-id>
    &base=main
```

If no pull request exists, the daemon calls:

```http
POST /repos/vikramsg/dotfiles/pulls
```

with:

```json
{
  "head": "ocint/<job-id>",
  "base": "main",
  "title": "ocint: complete job <job-id>",
  "body": "Automated by ocint daemon for <conversation-id>."
}
```

The returned pull request URL is stored as a job artifact. The job and its
terminal outbox update are then committed atomically as completed.

## 9. Verify Idempotency

Submit the same request again with the same idempotency key. The daemon must
return the existing job rather than create another session, branch, commit, or
pull request:

```bash
ocint daemon submit dotfiles \
  "<same-prompt>" \
  --actor vikram_orbio_earth \
  --idempotency-key daemon-bootstrap-v1
```

Also verify that GitHub reports exactly one open pull request for the generated
head branch.

## Acceptance Evidence

The first real run completed on July 16, 2026 with:

```text
Job:       a8ba177f91d64684a1f7d5a757738f70
Session:   ses_0934db182ffeZJCGKbaKL6df5K
Base:      c92ee3fc6b2d0021646c2296761f67d674a2d6a8
Branch:    ocint/a8ba177f91d64684a1f7d5a757738f70
Commit:    24628d9b76aec504a0fbac486c9edb5f5130602b
Pull request: https://github.com/vikramsg/dotfiles/pull/184
```

The pull request targeted `main`, changed only
`bin/ocint/DAEMON_ACCEPTANCE.md`, passed repository checks, and was reused when
the same idempotency key was submitted again.

The acceptance database and managed repository state were retained after the
services shut down so the complete durable workflow remains inspectable.
