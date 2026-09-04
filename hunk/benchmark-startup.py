#!/usr/bin/env python3
"""Measure process-level Hunk launcher startup without entering the TUI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Result:
    name: str
    median_ms: float
    p95_ms: float
    minimum_ms: float
    maximum_ms: float
    runs: int


def percentile_nearest_rank(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    rank = max(1, int(percentile * len(ordered) + 0.999999))
    return ordered[rank - 1]


def measure(name: str, command: list[str], warmups: int, runs: int) -> Result:
    for _ in range(warmups):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter_ns()
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)

    return Result(
        name=name,
        median_ms=statistics.median(samples),
        p95_ms=percentile_nearest_rank(samples, 0.95),
        minimum_ms=min(samples),
        maximum_ms=max(samples),
        runs=runs,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.runs < 1 or args.warmups < 0:
        parser.error("--runs must be positive and --warmups must not be negative")

    hunk = shutil.which("hunk")
    if hunk is None:
        parser.error("hunk is not available in PATH")

    home = Path.home()
    script = home / ".zsh_script"
    commands = [
        ("minimal-zsh", ["/bin/zsh", "-dfc", "true"]),
        ("interactive-zsh", ["/bin/zsh", "-ic", "true"]),
        ("native-hunk-version", [hunk, "--version"]),
        ("interactive-hunk-version", ["/bin/zsh", "-ic", "hunk --version"]),
    ]
    if script.is_file():
        commands.append(
            (
                "source-script-hunk-version",
                ["/bin/zsh", "-dfc", f'source "{script}"; hunk --version'],
            )
        )
        commands.append(
            (
                "absolute-hunk-version",
                [
                    "/bin/zsh",
                    "-dfc",
                    f'source "{script}"; HUNK_COMMAND_PATH="{hunk}" hunk --version',
                ],
            )
        )

    results = [measure(name, command, args.warmups, args.runs) for name, command in commands]
    if args.json:
        print(json.dumps({"platform": os.uname().sysname, "results": [asdict(r) for r in results]}, indent=2))
        return 0

    print(f"{'case':32} {'median':>10} {'p95':>10} {'min':>10} {'max':>10}")
    for result in results:
        print(
            f"{result.name:32} "
            f"{result.median_ms:9.1f}ms {result.p95_ms:9.1f}ms "
            f"{result.minimum_ms:9.1f}ms {result.maximum_ms:9.1f}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
