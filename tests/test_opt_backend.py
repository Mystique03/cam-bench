#!/usr/bin/env python3
"""Offline check for cam_bench.backends.opt - real subprocess/IPC against a stub
worker script (no optcam SDK or hardware needed), covering discover/open/capture/
set_control/close. Run: python tests/test_opt_backend.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cam_bench.backends import opt as opt_module
from cam_bench.backends.base import DeviceInfo
from cam_bench.backends.opt import OptBackend

_STUB_WORKER = r'''
import sys

if "--discover" in sys.argv:
    print("DEV D999|Stub OPT Camera", flush=True)
    sys.exit(0)

print("READY", flush=True)
last = {"exposure_us": None, "gain_db": None}
for line in sys.stdin:
    parts = line.strip().split()
    if not parts:
        continue
    if parts[0] == "CAPTURE":
        import tempfile, os, numpy as np
        fd, path = tempfile.mkstemp(suffix=".npy")
        os.close(fd)
        np.save(path, np.full((2, 2, 3), 7, dtype=np.uint8))
        print(f"OK {path}", flush=True)
    elif parts[0] == "SET" and len(parts) == 3:
        last[parts[1]] = float(parts[2])
        print("OK", flush=True)
    elif parts[0] == "QUIT":
        break
    else:
        print(f"ERR unknown command: {line.strip()!r}", flush=True)
'''


def check(name: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return condition


def main() -> int:
    all_ok = True
    tmpdir = Path(tempfile.mkdtemp())
    stub_path = tmpdir / "stub_opt_worker.py"
    stub_path.write_text(_STUB_WORKER)

    opt_module._WORKER_SCRIPT = stub_path
    os.environ["CAM_BENCH_OPT_PYTHON"] = sys.executable

    devices = OptBackend.discover()
    all_ok &= check("discover() parses 'DEV serial|label' lines from the worker",
                     len(devices) == 1 and devices[0].device_id == "D999"
                     and devices[0].backend == "opt")

    backend = OptBackend()
    backend.open(devices[0])
    frame = backend.get_frame()
    all_ok &= check("get_frame() returns the array the stub wrote via .npy handoff",
                     frame.shape == (2, 2, 3) and frame[0, 0, 0] == 7)

    backend.set_control("exposure_us", 8000)
    all_ok &= check("set_control() round-trips through the worker's OK reply",
                     backend.get_controls()["exposure_us"].value == 8000.0)

    backend.close()
    all_ok &= check("close() is idempotent", backend._proc is None)
    backend.close()  # must not raise

    del os.environ["CAM_BENCH_OPT_PYTHON"]
    all_ok &= check("discover() returns [] gracefully when CAM_BENCH_OPT_PYTHON is unset",
                     OptBackend.discover() == [])

    print()
    print("ALL PASS" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
