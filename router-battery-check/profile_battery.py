#!/usr/bin/env -S uv run --python 3.14t
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "requests",
#   "python-dotenv",
#   "tprof",
#   "pyobjc-framework-CoreWLAN",
# ]
# ///

import logging

import check_battery
import check_battery_sync
from tprof import tprof

# Silence the main scripts' logs to keep the profiling output clean
logging.getLogger("check_battery").setLevel(logging.WARNING)
logging.getLogger("check_battery_sync").setLevel(logging.WARNING)
# Also silence root logger if needed
logging.getLogger().setLevel(logging.WARNING)


def run_profile():
    # Targets for profiling: Top-level and sub-functions from both versions
    # We want to compare sync vs threaded versions of the same tasks
    sync_targets = [
        check_battery_sync.check_battery_sync,
        check_battery_sync.fetch_router_data,
        check_battery_sync.get_local_wifi_signal,
    ]

    threaded_targets = [
        check_battery.check_battery,
        check_battery.fetch_router_data,
        check_battery.get_local_wifi_signal,
    ]

    print("🎯 Profiling Synchronous execution (5 iterations)...", flush=True)
    with tprof(*sync_targets):
        for _ in range(5):
            check_battery_sync.check_battery_sync()

    print("\n🎯 Profiling Threaded execution (5 iterations)...", flush=True)
    with tprof(*threaded_targets):
        for _ in range(5):
            check_battery.check_battery()


if __name__ == "__main__":
    run_profile()
