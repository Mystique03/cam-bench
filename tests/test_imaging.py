#!/usr/bin/env python3
"""Offline check for cam_bench.imaging - synthetic frames only, no camera needed.
Run: python tests/test_imaging.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np

from cam_bench import imaging


def check(name: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return condition


def main() -> int:
    all_ok = True

    # sharp vs blurred synthetic frame - a real checkerboard has strong edges, a
    # heavily blurred copy of the same image should score measurably lower.
    checker = np.zeros((200, 200, 3), dtype=np.uint8)
    checker[::20, :] = 255
    checker[:, ::20] = 255
    blurred = cv2.GaussianBlur(checker, (25, 25), 0)

    sharp_score = imaging.focus_score(checker)
    blurred_score = imaging.focus_score(blurred)
    all_ok &= check("focus_score: sharp image scores higher than a blurred copy",
                     sharp_score > blurred_score * 2)

    flat = np.full((50, 50, 3), 128, dtype=np.uint8)
    all_ok &= check("focus_score: flat/blank image scores near zero",
                     imaging.focus_score(flat) < 1.0)

    hist = imaging.histogram(checker, bins=16)
    all_ok &= check("histogram: returns the requested bin count", len(hist) == 16)
    all_ok &= check("histogram: normalized so the tallest bin is 1.0", max(hist) == 1.0)
    all_ok &= check("histogram: all bins non-negative", all(v >= 0 for v in hist))

    clipped = np.full((10, 10, 3), 255, dtype=np.uint8)
    clipped[5:, :] = 0
    zebra = imaging.apply_zebra(clipped)
    all_ok &= check("apply_zebra: modifies a fully clipped frame (stripes applied)",
                     not np.array_equal(zebra, clipped))

    mid = np.full((10, 10, 3), 128, dtype=np.uint8)
    all_ok &= check("apply_zebra: leaves a well-exposed frame untouched",
                     np.array_equal(imaging.apply_zebra(mid), mid))

    print()
    print("ALL PASS" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
