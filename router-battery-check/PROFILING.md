# Profiling Results: Evolution of Performance

This document tracks the performance optimizations of `check_battery.py`, demonstrating the impact of concurrency and native API integration.

## Methodology

Profiling was performed using [tprof](https://github.com/adamchainz/tprof), leveraging Python 3.12+'s `sys.monitoring`. All results are based on 5 iterations.

---

## Phase 1: The Bottleneck Discovery (system_profiler)

Initial profiling revealed that the script was dominated by a single system call.

### 1. Synchronous Execution Breakdown
Executed with `system_profiler` for Wi-Fi probing.

| Function | Calls | Total Time | Mean ± σ |
| :--- | :--- | :--- | :--- |
| `check_battery_sync()` | 5 | 22.0s | **4.4s** ± 98ms |
| `get_local_wifi_signal()` | 5 | 20.5s | **4.1s** ± 95ms |
| `fetch_router_data()` | 15 | 1.35s | 90ms ± 73ms |

### 2. Threaded Execution Breakdown
Executed with `system_profiler` for Wi-Fi probing.

| Function | Calls | Total Time | Mean ± σ |
| :--- | :--- | :--- | :--- |
| `check_battery_threaded()` | 5 | 20.5s | **4.1s** ± 147ms |
| `get_local_wifi_signal()` | 5 | 20.5s | **4.1s** ± 148ms |
| `fetch_router_data()` | 15 | 3.90s | 261ms ± 117ms |

**Insight**: Threading "hid" the router API latency, but the script could never be faster than the 4.1s `system_profiler` call.

---

## Phase 2: WLAN Optimization (CoreWLAN)

We replaced the shell-based `system_profiler` with the native macOS `CoreWLAN` framework.

| Method | Avg. Time | Speedup |
| :--- | :--- | :--- |
| `system_profiler` (Shell) | 4,100ms | Baseline |
| `CoreWLAN` (Native) | **4ms** | **1,025x Faster** |

---

## Phase 3: Final Optimized Results

With the WLAN bottleneck removed, the script is now limited only by network I/O.

### 1. Synchronous Execution (Optimized)
| Function | Calls | Total Time | Mean ± σ |
| :--- | :--- | :--- | :--- |
| `check_battery_sync()` | 5 | 1.42s | **284ms** ± 14ms |
| `get_local_wifi_signal()` | 5 | 30ms | 6ms ± 5ms |

### 2. Threaded Execution (Optimized)
| Function | Calls | Total Time | Mean ± σ |
| :--- | :--- | :--- | :--- |
| `check_battery_threaded()` | 5 | 1.17s | **235ms** ± 51ms |
| `get_local_wifi_signal()` | 5 | 21ms | 4ms ± 0.7ms |

---

## Analysis & Conclusion

### Summary of Gains
- **Total Execution**: Reduced from **4,400ms** to **235ms**.
- **Efficiency**: Threading provides a ~17% improvement even in the optimized state by overlapping concurrent router API requests.
- **Architectural Shift**: Moving from shell-scraping to native APIs (`CoreWLAN`) provided the most significant performance leap (98% reduction in wall-clock time).

The project now maintains a high-performance profile suitable for frequent background execution.
