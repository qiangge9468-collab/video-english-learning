#!/usr/bin/env python3
"""Measure actual GPU memory before and after the v2.1.0 idle unload path."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERSION_DIR = ROOT / "tools" / "versions" / "v2.1.0"
sys.path.insert(0, str(VERSION_DIR))

import service  # noqa: E402


def gpu_memory_mib():
    completed = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    values = [int(line.strip()) for line in completed.stdout.splitlines() if line.strip()]
    return sum(values)


def main():
    before = gpu_memory_mib()
    wrapper = service.get_whisper_model()
    loaded = gpu_memory_mib()
    backend = wrapper.model
    released = service.release_idle_models(force=True)
    time.sleep(1.0)
    after = gpu_memory_mib()
    result = {
        "pid": os.getpid(),
        "total_gpu_memory_mib_before_load": before,
        "total_gpu_memory_mib_model_loaded": loaded,
        "total_gpu_memory_mib_after_idle_release": after,
        "gpu_memory_released_mib": max(0, loaded - after),
        "release_called": released,
        "backend_loaded_after_release": bool(getattr(backend, "model_is_loaded", False)),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not released or result["backend_loaded_after_release"]:
        raise SystemExit("Idle release did not unload the Whisper backend")


if __name__ == "__main__":
    main()
