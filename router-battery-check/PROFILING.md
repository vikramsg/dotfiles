# Profiling Results: Synchronous vs. Threaded Execution

This document details the performance comparison between sequential (synchronous) and parallel (threaded) execution in `check_battery.py`.

## Methodology

The profiling was performed using [tprof](https://github.com/adamchainz/tprof), which leverages Python 3.12's `sys.monitoring` for low-overhead targeted profiling.

### Comparison Focus
We compared two orchestration methods for data collection:
1. **Synchronous**: Executes router API calls and the local Wi-Fi probe one after another.
2. **Threaded**: Executes all API calls and the local Wi-Fi probe concurrently using `concurrent.futures.ThreadPoolExecutor`.

### Tooling
- **Profiler**: `tprof`
- **Runtime Manager**: `uv`
- **Execution**: Both versions were executed 5 times to generate reliable averages.

## Results

Executed on: 2026-01-29

| Function | Calls | Total Time | Mean ± σ | Min … Max | Delta |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `check_battery_sync()` | 5 | 22s | 4.4s ± 70ms | 4s … 4s | Baseline |
| `check_battery_threaded()` | 5 | 21s | 4.2s ± 106ms | 4s … 4s | -4.39% |

## Analysis & Insights

### 1. The Bottleneck: Local Wi-Fi Probe
The results show that `check_battery_threaded()` is only marginally faster than `check_battery_sync()`. 
- **Cause**: The execution time is dominated by the `get_local_wifi_signal()` function, which uses `system_profiler` and takes approximately 4.2 seconds to complete.
- **Threaded Behavior**: In the threaded version, the router API requests (which are very fast) finish almost immediately, but the entire `check_battery_threaded` function must still wait for the 4.2s `system_profiler` task to finish.

### 2. Concurrency Benefits
While the total wall-clock time reduction is small (~4-5%), threading effectively overlaps the network latency of three separate router API calls with the local system call. The performance gain is limited by the single longest-running blocking task (`system_profiler`).

## Conclusion
Threading provides a cleaner architectural separation and ensures network latency doesn't stack on top of system latency. However, to achieve significant speed improvements, the local Wi-Fi probing mechanism itself would need to be replaced with a faster alternative.
