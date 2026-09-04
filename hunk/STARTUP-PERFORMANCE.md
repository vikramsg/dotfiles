# Hunk startup performance experiments

This is the experimental log for reducing the delay between invoking the Herdr
Hunk popup and seeing the review. Each hypothesis is tested in its own commit.
Rejected experiments remain documented here even when their code change is not
retained.

## Success criteria

- Process-level launcher overhead: p95 at most 50 ms above native Hunk.
- Herdr popup to first Hunk frame: p95 at most 500 ms.
- If native Hunk itself exceeds 500 ms, stop when launcher overhead is at most
  50 ms and the remaining time is demonstrated to be native Hunk startup.
- Preserve zero-argument target selection, native argument delegation, review
  export, and clear error/no-change messages.

Process benchmarks use `hunk/benchmark-startup.py`, two warmups, and 20 measured
runs. Interactive TUI measurements use Herdr and record the command start and
first visible Hunk header.

## Baseline — 2026-09-04

Initial five-run shell measurements on macOS:

| Case | Warm result |
| --- | ---: |
| `/bin/zsh -fc true` | 0 ms |
| `/bin/zsh -ic true` | 240–250 ms |
| native `hunk --version` | 330–370 ms |
| `/bin/zsh -ic 'hunk --version'` | 580–620 ms |

The first interactive Hunk measurement was 920 ms, indicating an additional
cold-start penalty. The warm measurements attribute about 250 ms to interactive
Zsh initialization. `exec` is not itself the expensive operation.

Reproducible 20-run baseline (`python3 hunk/benchmark-startup.py`):

| Case | Median | p95 |
| --- | ---: | ---: |
| minimal no-rc Zsh | 8.2 ms | 13.5 ms |
| interactive Zsh | 310.2 ms | 329.5 ms |
| native `hunk --version` | 346.7 ms | 386.4 ms |
| interactive Zsh and Hunk | 610.1 ms | 685.9 ms |
| no-rc Zsh, `.zsh_script`, and Hunk | 405.3 ms | 419.1 ms |

## Experiment log

### H1 — Skip interactive Zsh initialization

**Hypothesis:** Herdr can source only the managed shell functions in a no-rc Zsh
and preserve behavior while removing approximately 250 ms of startup latency.

**Change:** Replace `zsh -ic hunk` with a no-rc Zsh that sources the managed
`.zsh_script` directly and invokes the same `hunk()` function.

**Process benchmark:**

| Launcher | Median | p95 |
| --- | ---: | ---: |
| current interactive launcher | 610.1 ms | 685.9 ms |
| no-rc launcher | 405.3 ms | 419.1 ms |
| native Hunk | 346.7 ms | 386.4 ms |

The candidate removes 266.8 ms (38.9%) at p95 and leaves 32.7 ms of launcher
overhead over native Hunk, meeting the 50 ms process-level target.

**End-to-end verification:** Passed for dirty working-tree selection, clean
feature-branch selection, no-change output, outside-repository errors, native
argument delegation, comment save, automatic JSON export, and keeping Hunk open.
One instrumented Herdr pane launch reached the first visible dirty-review frame
in 1917.4 ms. This timing includes two Herdr CLI invocations and is not directly
comparable to the process benchmark, but it proves the 500 ms end-to-end target
has not yet been demonstrated.

**Status:** Retained. The process-overhead target is met; continue the loop to
isolate native TUI, extension, Git, and Herdr costs.

### H2 — Source only a dedicated Hunk function file

**Hypothesis:** Parsing unrelated functions in `.zsh_script` materially delays
the lightweight launcher, so extracting `hunk()` would improve startup.

**Isolation benchmark (20 runs, two warmups):**

| No-rc Zsh command | Median | p95 |
| --- | ---: | ---: |
| `hunk --version` without sourcing `.zsh_script` | 401.8 ms | 411.8 ms |
| source `.zsh_script`, then `hunk --version` | 404.3 ms | 428.6 ms |

The full script added 2.5 ms at the median and 16.8 ms at p95. That is not the
dominant remaining delay and is below the launcher-overhead budget. Extracting
the function would add another installed file and synchronization point for a
small, noisy gain.

**Status:** Rejected. Keep the shared function in `.zsh_script`.

### H3 — Avoid PATH search for the managed Hunk binary

**Hypothesis:** Resolving `hunk` through the inherited PATH is a meaningful part
of lightweight shell overhead. Herdr can provide the managed
`$HOME/.local/bin/hunk` path without changing interactive delegation.

**Isolation benchmark (20 runs, two warmups):**

| Command | Median | p95 |
| --- | ---: | ---: |
| no-rc Zsh resolves `hunk` through PATH | 362.2 ms | 416.7 ms |
| no-rc Zsh invokes absolute Hunk path | 343.5 ms | 368.3 ms |
| direct absolute Hunk path | 351.1 ms | 389.6 ms |

The absolute path reduced p95 by 48.4 ms in the shell comparison. The managed
npm installation is explicitly configured at `$HOME/.local/bin` on both macOS
and Linux. `HUNK_COMMAND_PATH` affects only the Herdr invocation; normal
interactive `hunk` calls continue to resolve the native command through PATH.

The first implementation tried Hunk's existing `HUNK_BIN_PATH` variable. The
npm wrapper interprets that as an override for its packaged native binary, so
pointing it back at the npm wrapper caused recursion. The experiment therefore
uses the dotfiles-only `HUNK_COMMAND_PATH` name.

**Integrated process benchmark (20 runs, two warmups):**

| Lightweight launcher | Median | p95 |
| --- | ---: | ---: |
| PATH-resolved Hunk | 389.0 ms | 509.5 ms |
| absolute managed Hunk | 384.2 ms | 416.3 ms |

The median difference was small under this run's system load, while p95 improved
by 93.2 ms. Syntax, config validation, native argument delegation, and a real
dirty-review TUI launch passed. The Herdr pane-to-frame sample was 2727.4 ms and
remained too noisy to attribute to this path change.

**Status:** Retained. Continue by measuring the npm wrapper against its packaged
native executable and by building a repeatable first-frame measurement.

### H4 — Bypass the npm wrapper for the Herdr TUI

**Hypothesis:** The JavaScript npm launcher contributes material startup time
before it starts Hunk's packaged native executable.

**Interleaved isolation benchmark (50 runs each, three warmups):**

| Executable | Median | p95 |
| --- | ---: | ---: |
| npm `hunk` wrapper | 374.1 ms | 464.2 ms |
| packaged native Hunk | 281.1 ms | 314.4 ms |

The native executable improved median by 93.0 ms and p95 by 149.8 ms. `just
hunk` now resolves the platform package at install time and maintains
`~/.local/bin/hunk-native`; Herdr uses that symlink. The normal `hunk` command
and its special wrapper commands remain unchanged.

**Integrated process benchmark (20 runs, two warmups):**

| Lightweight launcher target | Median | p95 |
| --- | ---: | ---: |
| npm wrapper | 358.8 ms | 495.1 ms |
| packaged native Hunk | 304.8 ms | 330.7 ms |

This run improved median by 54.0 ms and p95 by 164.4 ms. The complete native
launcher is now only 16.3 ms above the isolated packaged-native p95 from the
interleaved benchmark, meeting the 50 ms process-overhead target.

The installed native path passed config and shell validation, dirty-tree target
selection, real TUI rendering, comment editing, and automatic review export. A
single Herdr pane-to-frame sample took 2353.5 ms, confirming that process launch
is no longer the dominant end-to-end cost.

**Status:** Retained. Continue by isolating native TUI startup with and without
extensions, Git target selection, and Herdr pane creation.

### H5 — Disable user extensions during startup

**Hypothesis:** Loading the review workflow extension delays Hunk's first frame.

**Interleaved Herdr pane benchmark (10 runs each, one warmup):**

| Native Hunk TUI | Median | p95 | Minimum |
| --- | ---: | ---: | ---: |
| normal extensions | 2042.7 ms | 3030.1 ms | 1770.7 ms |
| `--no-extensions` | 2166.9 ms | 4911.9 ms | 1982.9 ms |

Each sample starts timing immediately before `herdr pane run` and stops when a
fresh pane exposes the Hunk working-tree header. The tails are noisy, but
disabling extensions did not improve the median or minimum. The extension is
therefore not on the initial-render critical path in a meaningful way.

**Status:** Rejected. Keep the review workflow extension enabled.

### H6 — Rewrite Git target selection

**Hypothesis:** The zero-argument wrapper's Git probes materially delay the
working-tree first frame.

**Interleaved Herdr pane benchmark (10 runs each, one warmup):**

| Native TUI path | Median | p95 | Minimum |
| --- | ---: | ---: | ---: |
| direct `hunk-native diff` | 2187.5 ms | 2390.1 ms | 1675.7 ms |
| complete zero-argument target selector | 2185.2 ms | 2409.2 ms | 1980.7 ms |

The medians differ by 2.3 ms in favor of the complete selector and p95 differs
by 19.1 ms in favor of direct launch, both below run-to-run noise. Fifty-run
process isolation measured `git rev-parse --show-toplevel` at 21.4 ms median /
26.5 ms p95 and dirty `git status` at 24.2 ms / 29.2 ms in the test repository.

**Status:** Rejected. Preserve the simpler, already-tested Git behavior rather
than replacing it with less readable early-exit probes.
