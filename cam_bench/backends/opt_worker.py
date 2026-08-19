#!/usr/bin/env python3
"""OPT Machine Vision USB3 camera worker (child process) - run under whichever
Python interpreter has the vendor `optcam` SDK installed (set CAM_BENCH_OPT_PYTHON
to that interpreter's path). See backends/opt.py for why this runs as a separate
process instead of an in-process import: `optcam` is a compiled wheel tagged to
one CPython minor version, which won't generally match the app's own interpreter.

Two modes:
  --discover              print one "DEV <serial>|<label>" line per camera, then exit
  --serial S [--exposure-us N] [--gain-db N]   persistent capture worker

Persistent-worker line protocol (stdout is protocol-only; diagnostics go to stderr):
  worker -> parent, on startup: "READY" or "ERR <message>"
  parent -> worker: "CAPTURE"                    -> "OK <path-to-.npy>" or "ERR <message>"
  parent -> worker: "SET <exposure_us|gain_db> <value>" -> "OK" or "ERR <message>"
  parent -> worker: "QUIT"
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import tempfile

import cv2
import numpy as np
import optcam

FRAME_WAIT_TIMEOUT_SEC = 1.5


def _frame_wait_sec(cam) -> float:
    # A dark scene needs a long exposure, and the frame cannot arrive before the
    # exposure ends - so the wait has to track it, not a fixed 1.5s.
    try:
        exposure_sec = float(cam.exposure_us) / 1e6
    except Exception:  # noqa: BLE001 - control may be unreadable; fall back to the floor
        exposure_sec = 0.0
    return max(FRAME_WAIT_TIMEOUT_SEC, exposure_sec * 2 + 0.5)


def _bayer_demosaic_code(pixel_type):
    return {
        optcam.PixelType.BAYER_GR8: cv2.COLOR_BAYER_GB2BGR,
        optcam.PixelType.BAYER_RG8: cv2.COLOR_BAYER_BG2BGR,
        optcam.PixelType.BAYER_GB8: cv2.COLOR_BAYER_GR2BGR,
        optcam.PixelType.BAYER_BG8: cv2.COLOR_BAYER_RG2BGR,
    }.get(pixel_type)


def raw_to_bgr(arr: np.ndarray, pixel_type) -> np.ndarray:
    if arr.dtype == np.uint16:
        arr = (arr >> 8).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    code = _bayer_demosaic_code(pixel_type)
    if code is not None:
        return cv2.cvtColor(arr, code)
    if pixel_type == optcam.PixelType.RGB8:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    return arr


def reply(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def run_discover() -> int:
    for dev in optcam.discover():
        serial = getattr(dev, "serial", None) or str(dev)
        label = getattr(dev, "model", None) or "OPT camera"
        reply(f"DEV {serial}|{label}")
    return 0


def run_worker(args: argparse.Namespace) -> int:
    try:
        cam = optcam.Camera.open_serial(args.serial)
    except Exception as e:  # noqa: BLE001
        reply(f"ERR failed to open serial {args.serial}: {e}")
        return 1

    frame_q: "queue.Queue[tuple[np.ndarray, object]]" = queue.Queue(maxsize=1)

    def on_frame(frame) -> None:
        try:
            raw = frame.numpy().copy()
            pf = frame.pixel_type
        except Exception:  # noqa: BLE001
            return
        try:
            frame_q.put_nowait((raw, pf))
        except queue.Full:
            try:
                frame_q.get_nowait()
                frame_q.put_nowait((raw, pf))
            except queue.Empty:
                pass

    try:
        cam.trigger = optcam.TriggerMode.SOFTWARE
        try:
            cam.set_enum("ExposureAuto", "Off")
            cam.set_enum("GainAuto", "Off")
        except optcam.Error:
            pass
        if args.exposure_us is not None:
            cam.exposure_us = args.exposure_us
        if args.gain_db is not None:
            cam.gain_db = args.gain_db
        cam.buffer_count = 4
        cam.start(on_frame)
    except Exception as e:  # noqa: BLE001
        reply(f"ERR failed to configure/start camera: {e}")
        return 1

    reply("READY")

    try:
        for line in sys.stdin:
            parts = line.strip().split()
            if not parts:
                continue
            cmd = parts[0]
            if cmd == "CAPTURE":
                while not frame_q.empty():
                    frame_q.get_nowait()
                try:
                    cam.software_trigger()
                    wait_sec = _frame_wait_sec(cam)
                    raw, pf = frame_q.get(timeout=wait_sec)
                except queue.Empty:
                    reply(f"ERR no frame within {wait_sec:g}s of trigger")
                    continue
                except Exception as e:  # noqa: BLE001
                    reply(f"ERR trigger failed: {e}")
                    continue
                bgr = raw_to_bgr(raw, pf)
                fd, path = tempfile.mkstemp(suffix=".npy", prefix="optcam_")
                os.close(fd)
                np.save(path, bgr)
                reply(f"OK {path}")
            elif cmd == "SET" and len(parts) == 3:
                name, value = parts[1], parts[2]
                try:
                    if name == "exposure_us":
                        cam.exposure_us = float(value)
                    elif name == "gain_db":
                        cam.gain_db = float(value)
                    else:
                        reply(f"ERR unknown control {name!r}")
                        continue
                    reply("OK")
                except Exception as e:  # noqa: BLE001
                    reply(f"ERR set {name} failed: {e}")
            elif cmd == "QUIT":
                break
            else:
                reply(f"ERR unknown command: {line.strip()!r}")
    finally:
        try:
            cam.stop()
        finally:
            cam.close()

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--serial", default=None)
    ap.add_argument("--exposure-us", type=float, default=None)
    ap.add_argument("--gain-db", type=float, default=None)
    args = ap.parse_args()

    if args.discover:
        return run_discover()
    if not args.serial:
        reply("ERR --serial required unless --discover")
        return 1
    return run_worker(args)


if __name__ == "__main__":
    sys.exit(main())
