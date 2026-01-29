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
Environment: Python 3.14.2 (freethreaded)

### 1. Synchronous Execution Breakdown
Total time for 5 iterations.

| Function | Calls | Total Time | Mean ± σ | Min … Max |
| :--- | :--- | :--- | :--- | :--- |
| `check_battery_sync()` | 5 | 22s | 4.4s ± 98ms | 4.4s … 4.4s |
| `get_local_wifi_signal()` | 5 | 20s | 4.1s ± 95ms | 4.1s … 4.1s |
| `fetch_router_data()` | 15 | 1.35s | 90ms ± 73ms | 11ms … 207ms |

### 2. Threaded Execution Breakdown
Total time for 5 iterations.

| Function | Calls | Total Time | Mean ± σ | Min … Max |
| :--- | :--- | :--- | :--- | :--- |
| `check_battery_threaded()` | 5 | 20.5s | 4.1s ± 147ms | 4.1s … 4.1s |
| `get_local_wifi_signal()` | 5 | 20.5s | 4.1s ± 148ms | 4.1s … 4.1s |
| `fetch_router_data()` | 15 | 3.9s | 261ms ± 117ms | 63ms … 590ms |

## Analysis & Insights

### 1. The Bottleneck: Local Wi-Fi Probe
The detailed function profiling confirms that `get_local_wifi_signal()` is the primary bottleneck in both versions.
- **Duration**: It consistently takes ~4.1 seconds.
- **Impact**: In the synchronous version, it accounts for ~93% of the total execution time.

### 2. Concurrency Efficiency
In the threaded version, the router API calls (`fetch_router_data`) and the Wi-Fi probe run concurrently.
- **Overlap**: Even though `fetch_router_data` latency increased in the threaded environment (likely due to thread management or network contention), it is entirely "hidden" behind the 4.1s execution time of the Wi-Fi probe.
- **Wall-clock Gain**: The total time for `check_battery_threaded` matches the time of `get_local_wifi_signal` almost exactly, proving that all other tasks finished within that window.

## Conclusion
Threading provides a cleaner architectural separation and ensures network latency doesn't stack on top of system latency. However, to achieve significant speed improvements, the local Wi-Fi probing mechanism itself would need to be replaced with a faster alternative.
