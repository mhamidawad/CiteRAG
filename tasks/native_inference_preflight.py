#!/usr/bin/env python3
"""Host-only, read-only resource gate before a bounded local model inference."""
import json
import math
import os
import shutil
import sys
from pathlib import Path

# Conservative, reviewed defaults for the Oracle VM; this tool never invokes AI.
MIN_MEMORY_AVAILABLE_MIB = 5 * 1024
MIN_SWAP_FREE_MIB = 1024
MAX_LOAD_RATIO = 0.50   # 1-minute load divided by number of CPUs
MAX_ROOT_DISK_USED_PERCENT = 85.0


class PreflightError(RuntimeError):
    pass


def snapshot(meminfo="/proc/meminfo", loadavg="/proc/loadavg", disk="/"):
    """Read host resource signals; fail closed if any is inaccessible."""
    if Path("/.dockerenv").exists():
        raise PreflightError("HOST_ONLY: do not use host /proc thresholds inside Docker")
    try:
        values = {}
        for line in Path(meminfo).read_text(encoding="ascii").splitlines():
            key, sep, value = line.partition(":")
            if sep and key in {"MemAvailable", "SwapFree"}:
                values[key] = int(value.split()[0]) // 1024
        if values.keys() != {"MemAvailable", "SwapFree"}:
            raise PreflightError("Missing memory accounting fields")
        load1 = float(Path(loadavg).read_text(encoding="ascii").split()[0])
        cores = os.cpu_count()
        usage = shutil.disk_usage(disk)
        if not cores or usage.total <= 0 or not math.isfinite(load1):
            raise PreflightError("Invalid CPU/load/disk accounting")
        return {
            "available_memory_mib": values["MemAvailable"],
            "free_swap_mib": values["SwapFree"],
            "load_1m": load1,
            "logical_cores": cores,
            "disk_used_percent": round(usage.used / usage.total * 100, 1),
        }
    except (OSError, ValueError, IndexError, ZeroDivisionError) as exc:
        raise PreflightError("Resource observation unavailable") from exc


def assess(data):
    """Return actionable blocker codes without guessing or side effects."""
    required = ("available_memory_mib", "free_swap_mib", "load_1m",
                "logical_cores", "disk_used_percent")
    if any(k not in data for k in required):
        return {"ready": False, "blockers": ["INCOMPLETE_RESOURCE_SNAPSHOT"]}
    try:
        mem = float(data["available_memory_mib"])
        swap = float(data["free_swap_mib"])
        load = float(data["load_1m"])
        cores = int(data["logical_cores"])
        disk = float(data["disk_used_percent"])
    except (TypeError, ValueError, OverflowError):
        return {"ready": False, "blockers": ["INVALID_RESOURCE_SNAPSHOT"]}
    if cores <= 0 or any(not math.isfinite(x) for x in (mem, swap, load, disk)):
        return {"ready": False, "blockers": ["INVALID_RESOURCE_SNAPSHOT"]}
    blockers = []
    if mem < MIN_MEMORY_AVAILABLE_MIB:
        blockers.append("MEMORY_HEADROOM_LOW")
    if swap < MIN_SWAP_FREE_MIB:
        blockers.append("SWAP_HEADROOM_LOW")
    if load / cores > MAX_LOAD_RATIO:
        blockers.append("CPU_LOAD_HIGH")
    if disk >= MAX_ROOT_DISK_USED_PERCENT:
        blockers.append("DISK_NEAR_LIMIT")
    return {"ready": not blockers, "blockers": blockers}


def main():
    try:
        readings = snapshot()
        result = assess(readings)
        output = {"status": "READY" if result["ready"] else "BLOCKED",
                  "reason_codes": result["blockers"], "snapshot": readings,
                  "inference_started": False}
    except PreflightError as exc:
        output = {"status": "BLOCKED", "reason_codes": [str(exc)],
                  "inference_started": False}
    print(json.dumps(output, sort_keys=True))
    return 0 if output["status"] == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
