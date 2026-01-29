#!/usr/bin/env -S uv run --python 3.13
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
    # Targets for profiling: Comparing Sync vs Threaded
    targets = [
        check_battery.check_battery_sync,
        check_battery.check_battery_threaded,
    ]

    print("🎯 Comparing Synchronous vs Threaded execution (5 iterations)...")

    with tprof(*targets, compare=True):
        for i in range(5):
            check_battery.check_battery_sync()
            check_battery.check_battery_threaded()


if __name__ == "__main__":
    run_profile()
