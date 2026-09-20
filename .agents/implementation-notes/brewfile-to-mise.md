# Implementation Notes: Repo Trim + Replace `Brewfile` with mise

Plan: `.agents/plans/brewfile-to-mise.md` (frozen; not edited after approval).
Branch: `chore/mise-replace-brewfile`.

---

## Decisions taken that we had not already agreed

### 1. `fd` replaced with `rg --files` rather than a `find` pipeline

- **Decision:** `fz()` in `zsh/.zsh_script` now sets `visible_files='rg --files'`.
- **Why:** The plan said to replace the `fd` line but did not name a replacement. `rg --files`
  reproduces `fd`'s relevant behaviour exactly — respects `.gitignore`, excludes `.git`, and already
  emits paths without a leading `./` (so no `--strip-cwd-prefix` equivalent is needed). The existing
  `hidden_files="$visible_files --hidden"` line keeps working unmodified because `rg --files --hidden`
  is valid. `ripgrep` is staying in the tool set, so this adds no dependency. A `find` fallback would
  have needed a separate `hidden_files` definition and would not respect `.gitignore`.
- **Where:** `zsh/.zsh_script` (the `fz()` function).

### 2. `vm-tab` keeps `-o ClearAllForwardings=yes` after dropping autossh

- **Decision:** The plain `ssh` invocation retains `-o ClearAllForwardings=yes`.
- **Why:** The flag was not autossh-specific. Its purpose is to stop a second VM tab from trying to
  bind the shared `LocalForward` ports owned by `vm.dotfiles`, which is what
  `ssh/config.vm.shared` documents. Dropping it would reintroduce `Address already in use` between
  tabs.
- **Where:** `zsh/.zsh_script` (the `vm-tab()` function).

### 3. `LAUNCHD_PATH` converted from a module constant into `build_launchd_path(home)`

- **Decision:** Removed the import-time `LAUNCHD_PATH` constant; added
  `build_launchd_path(home: Path) -> str` and a keyword-only `home: Path | None = None` parameter on
  `build_launch_agent_service_plist`.
- **Why:** The constant was computed from `Path.home()` at import time, which made it impossible to
  test with a fake home. This is a direct consequence of the test-hygiene review: the test could only
  assert the developer's real home directory. Behaviour in production is unchanged because the
  default path goes through the existing `get_home_directory(None)` helper, which falls back to `HOME`.
  No compatibility shim was left behind for the old constant.
- **Where:** `bin/lch/lch/launchd.py`.

### 4. `bin/lch/tests/test_lch_launchd.py` split rather than rewritten in place

- **Decision:** The single service-plist test was split: the persistence-policy assertions stay, and
  the PATH assertion moved into a new
  `test_build_service_plist_supplies_a_path_that_resolves_the_service_commands` that uses an explicit
  fake home.
- **Why:** The original asserted the whole PATH as one literal — a change-detection test. The new test
  asserts the property that matters (the PATH reaches the directories the service resolves commands
  from) and derives its expectation from a supplied fake home.
- **Where:** `bin/lch/tests/test_lch_launchd.py`.

### 5. Test namespaces changed from `com.vikramsg.dotfiles` to `com.example.test`

- **Decision:** Every test fixture in `bin/lch/tests/` that used the repository's real launchd
  namespace now uses `com.example.test`.
- **Why:** Raised by the hygiene review. Tests should prove that labels derive from the supplied
  configuration, not restate the owner's personal default. This is a test-fixture change only;
  `DEFAULT_NAMESPACE` in `bin/lch/lch/config.py` is untouched.
- **Where:** `bin/lch/tests/*.py` (4 files).

### 6. `bin/opener_tunnel/tests/test_server.py` given a short-socket fixture

- **Decision:** Added a `socket_dir` fixture using `tempfile.TemporaryDirectory(dir="/tmp")` and
  switched three tests from `tmp_path` to it.
- **Why:** Not in the plan and not raised initially by the reviewer, but found while running the
  suite: Unix socket paths are capped near 104 characters and pytest's `tmp_path` under macOS
  `/private/var/folders/...` produces ~124-character paths. Five tests failed or passed depending on
  the machine's `TMPDIR`. That is a hermeticity defect, so it was fixed rather than worked around.
- **Where:** `bin/opener_tunnel/tests/test_server.py`.

### 7. Archived ZWM/ghostty test fixtures sanitized

- **Decision:** Renamed `meanderx`→`example`, `kunda`/`knda`→`project`, `/home/vikram`→`/home/user`,
  `orbio-github`→`work-github`, `infra`→`services` across `archive/`.
- **Why:** The archive is new content in this branch and is tracked, so moving files in did not
  reduce their exposure. The archived Go tests never assert a hash value — session names are only
  parsed structurally — so a uniform rename is safe. Verified by running `go test ./...` in
  `archive/bin/zwm`: all packages pass.
- **Where:** `archive/bin/zwm/**`, `archive/bin/ghostty_workspace/tests/**`,
  `archive/ghostty/workspaces/*.toml`.

### 8. `opencode/opencode.json` `resourceName` change reverted

- **Decision:** I first genericized `"orbio-p-eastus2-openai"` to `"example-openai-resource"`, then
  reverted it.
- **Why:** This is functional Azure provider configuration, not documentation. The value sits beside a
  `baseURL` in `providers.azure.settings`, and I could not establish that `resourceName` is unused —
  if the provider derives an endpoint from it, genericizing would silently break model access. A name
  leak the owner can choose to accept is better than a broken provider. Flagged below for a decision.
- **Where:** `opencode/opencode.json:62`.

### 9. `mise trust` left in the bootstrap unverified

- **Decision:** `just mise` runs `mise trust "$HOME/.config/mise/config.toml"` before `mise install`.
- **Why:** The plan flagged this as unverified (open question 4). It is included because `mise install`
  fails on an untrusted config and a symlinked global config is the case where trust is least likely
  to be implicit. If it turns out to be unnecessary it is a harmless no-op; the alternative — omitting
  it and having `mise install` fail on a fresh machine — is worse.
- **Where:** `justfile` (`mise` recipe).

---

## Files changed

**Archived (`git mv`, history preserved)**
`zwm/`, `bin/zwm/`, `bin/ghostty_workspace/`, `ghostty/workspaces/` → `archive/…`;
`.agents/plans/hunk-zsh-migration.md` → `archive/`.
New: `archive/README.md`.

**Deleted**
`television/`, `hunk/`, `bin/hunk-review/`, `bin/lc`, `Brewfile`.

**Added**
`mise/config.toml`.

**Edited**
`justfile`, `lch/config.toml`, `zed/settings.json`, `zed/RESTORE.md`, `ghostty/config`,
`ghostty/README.md`, `ssh/config.vm.shared`, `ssh/README.md`, `zsh/.zshrc`, `zsh/.zsh_script`,
`tmux/tmux.conf`, `herdr/config.toml`, `bin/README.md`, `bin/lch/lch/launchd.py`,
`bin/lch/tests/*.py`, `bin/screenshot/tests/test_screenshot_config.py`,
`bin/opener_tunnel/tests/test_config.py`, `bin/opener_tunnel/tests/test_server.py`,
`bin/ocint/AGENTS.md`, `opencode/sandbox/ROADMAP.md`, `README.md`, `herdr/README.md`,
`tuicr/README.md`, `macflow/BOOTSTRAP.md`, `opencode/docs/cursor.md`,
`.agents/plans/{go-icat-replica-experiments,go-terminal-image-renderer,slack,zwm-decisions}.md`.

---

## Review round 1 — findings and fixes

A review agent was run against the branch diff. Four findings, all confirmed and fixed:

### R1. `mise/config.toml` did not select the conda backend (broken)

- **Finding:** `imagemagick = { version = "latest", backend = "conda:imagemagick" }` does not work.
  `backend` is not a supported `[tools]` option; backend selection is part of the tool *key*.
- **Confirmed against the mise docs:** the conda backend page documents exactly
  `"conda:imagemagick" = "latest"`. The `backend` key form appears nowhere.
- **Fix:** replaced with `"conda:imagemagick" = "latest"`, matching the `"conda:chafa"` entry
  already in the file.
- **Note:** this defect came from the approved plan, which specified the invalid form. Following the
  plan literally is what produced it.

### R2. The `hunk()` shell function survived the Hunk removal

- **Finding:** `zsh/.zsh_script` still defined a `hunk()` wrapper invoking `command hunk` in three
  places, after this branch deleted Hunk entirely.
- **Fix:** deleted the whole function.

### R3. `ghostty/README.md` documented the archived `ghostty-workspace`

- **Finding:** a subsection pointed at `ghostty/workspaces/example.toml` and described configuring the
  CLI, both of which moved to `archive/`.
- **Fix:** removed the subsection, keeping the `ghostty/script.md` reference and the note about the
  `window-new-tab-position = end` setting, which is still live.

### R4. `pyproject.toml` still declared the archived package

- **Finding:** `bin/ghostty_workspace` remained in `[tool.uv.workspace].members` and
  `bin/ghostty_workspace/tests` in `testpaths`, though the path no longer exists. `uv` tolerates this,
  so it was stale configuration rather than an immediate failure.
- **Fix:** removed both entries.

### Confirmed clean by the same review

`justfile` `mise` recipe syntax and shell-invocation structure; the `ssh` and `rg --files`
replacements in `zsh/.zsh_script`; the PATH wiring in `tmux/tmux.conf` and `bin/lch/lch/launchd.py`;
the `zed/settings.json` escaping and hash derivation; and the `mise/config.toml` file location
against the repo's existing configuration pattern.

---

## Verification performed

| Check | Result |
|---|---|
| `just --list` | `mise` present; `brew`, `zwm`, `hunk`, `television` gone |
| `zsh -n zsh/.zsh_script` / `zsh/.zshrc` | pass |
| `zed/settings.json` parses (comments + trailing commas stripped) | pass |
| `herdr config check` | `config: ok` |
| `pytest bin/lch/tests` | 51 passed |
| `pytest bin/screenshot/tests bin/opener_tunnel/tests` | 48 passed (was 43 passed / 5 failed before the socket fixture) |
| `go test ./...` in `archive/bin/zwm` | all packages ok |
| Full `pytest` | 700 passed, 11 failed |

**The 11 failures are pre-existing and environmental.** All are in `bin/ocint/tests/` and fail because
`bin/ocint/ocint/daemon/lch/systemd.py:326` raises `RuntimeError("ocint daemon lch requires Linux")`.
This is an Intel macOS host; those tests target the Linux VM. No `bin/ocint` source or test file was
modified by this branch (only `bin/ocint/AGENTS.md`, a documentation file).

---

## What I could not do

**`just mise` was never executed.** Installing mise and running `mise install` was judged out of
scope for a branch that should be reviewable and reversible: it would modify the host (`brew install
mise`) and download 20 tools including a conda-packaged ImageMagick. Consequently the following
remain unverified:

- Whether mise's `conda:` backend installs `imagemagick` and `chafa` on macOS at all.
- Whether `imagemagick = { version = "latest", backend = "conda:imagemagick" }` is accepted syntax,
  versus the alternative form `"conda:imagemagick" = "latest"`.
- Whether `"github:RivoLink/leaf" = { version = "latest", bin = "leaf" }` correctly selects the
  `leaf-macos-x86_64` asset.
- Whether `mise trust` is required.

`magick -version` is the single check that settles the most important of these.

**The PATH propagation in 2d is untested end to end.** The shims directory was added to
`zsh/.zshrc`, `tmux/tmux.conf:97` and `bin/lch/lch/launchd.py`. Whether tmux's status line and
`lch-opener-tunnel` actually resolve tools through it cannot be confirmed until mise is installed —
before that, the shims directory does not exist.

---

## PII

Removed: archived fixtures (see decision 7), tracked plan files, `zed/RESTORE.md`,
`bin/ocint/AGENTS.md`, `opencode/sandbox/ROADMAP.md`, `bin/opener_tunnel/tests/test_config.py`,
and the PATH literal in `bin/lch/tests/test_lch_launchd.py`.

**Still present, and deliberately not changed.** These are functionally coupled to private
infrastructure — genericizing them would break the owner's working setup rather than merely
cosmetically tidy the repository, and the original values would be lost:

| Location | Value | Why it is functional |
|---|---|---|
| `zed/settings.json:52-112` | `/home/vikram_orbio_earth/...`, `orbio`, `meanderx`, `kunda` | Zed remote project list and SSH connection definitions |
| `opener_tunnel/config.toml:35` | `/home/vikram_orbio_earth/.opener.sock` | Remote socket path that must match the VM exactly for the SSH `-R` forward |
| `ssh/config.vm.shared:45,47,82` and `ssh/README.md` | `vm.kunda`, `kunda` | Live SSH aliases and tmux session names |
| `opencode/opencode.json:62` | `orbio-p-eastus2-openai` | Azure provider resource name (see decision 8) |

The `kunda` alias is the one inconsistency I introduced: the archived workspace files now say
`vm.project` while the live SSH config still says `vm.kunda`. Renaming the live alias would change a
name the owner types daily.

---

## For review

1. **`rg --files` as the `fd` replacement** (decision 1). Does it preserve the `fz()` behaviour you
   rely on — in particular `.gitignore` handling and the hidden-files toggle?
2. **`build_launchd_path` signature change** (decision 3). This removes a public module constant. Check
   nothing outside `bin/lch` imported it, and that the `home` parameter threading is what you want
   rather than a different injection point.
3. **The four functional PII items above.** Decide per item whether to genericize, move to an untracked
   local file, or accept. I did not want to make that call silently.
4. **`mise/config.toml` correctness.** Especially the `imagemagick` forced-backend syntax and the
   `leaf` bin option — unverified, see "What I could not do".
5. **Whether `just mise` should have been run.** If you want the conda-backend question settled before
   merge, it needs a deliberate host change.
6. **Scope.** This branch mixes a repo trim, six tool removals, a package-manager swap, a PII sweep
   and a test-hygiene pass. The plan justified the ordering, but the PII and test changes were added
   after the plan was frozen and are not in it.
