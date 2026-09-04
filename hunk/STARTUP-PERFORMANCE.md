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
