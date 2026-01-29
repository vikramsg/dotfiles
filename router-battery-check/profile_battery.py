#!/usr/bin/env -S uv run --python 3.14t
# /// script
# dependencies = [
#   "requests",
#   "python-dotenv",
#   "tprof",
# ]
# ///

import check_battery
from tprof import tprof
import logging

# Silence the main script's logs to keep the profiling output clean
logging.getLogger("check_battery").setLevel(logging.WARNING)
# Also silence root logger if needed
logging.getLogger().setLevel(logging.WARNING)


def run_profile():
    # Targets for profiling: Top-level and sub-functions
    targets = [
        check_battery.check_battery_sync,
        check_battery.check_battery_threaded,
        check_battery.fetch_router_data,
        check_battery.get_local_wifi_signal,
    ]

    print("🎯 Profiling Synchronous execution (5 iterations)...", flush=True)
    with tprof(*targets):
        for _ in range(5):
            check_battery.check_battery_sync()

    print("\n🎯 Profiling Threaded execution (5 iterations)...", flush=True)
    with tprof(*targets):
        for _ in range(5):
            check_battery.check_battery_threaded()


if __name__ == "__main__":
    run_profile()
