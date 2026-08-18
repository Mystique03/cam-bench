#!/usr/bin/env python3
"""Offline check for cam_bench.roi export - confirms the Iwata export shape matches
lcd_inspection/camera.py's load_camera_specs() field names exactly (fallback_rect /
calibrated_quad / calibrated_polygon + warp_size), since that's the whole point of
this export format. Run: python tests/test_roi_export.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cam_bench.roi import Roi, to_generic_json_dict, to_iwata_yaml_dict


def check(name: str, condition: bool) -> bool:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return condition


def main() -> int:
    all_ok = True

    rect_roi = Roi(shape="rect", points=[(10, 20), (110, 120)], image_w=200, image_h=200)
    rect_out = to_iwata_yaml_dict(rect_roi)
    all_ok &= check("rect export uses the 'fallback_rect' key with x/y/w/h",
                     rect_out == {"fallback_rect": {"x": 10, "y": 20, "w": 100, "h": 100}})

    quad_pts = [(302.0, 43.0), (290.0, 225.0), (1008.0, 599.0), (1020.0, 247.0)]
    quad_roi = Roi(shape="quad", points=quad_pts, image_w=1280, image_h=720)
    quad_out = to_iwata_yaml_dict(quad_roi)
    all_ok &= check("quad export uses 'calibrated_quad' + 'warp_size' keys",
                     "calibrated_quad" in quad_out and quad_out["warp_size"] == {"w": 1280, "h": 720})
    all_ok &= check("quad export preserves point order and count",
                     len(quad_out["calibrated_quad"]) == 4
                     and quad_out["calibrated_quad"][0] == [302.0, 43.0])

    poly_roi = Roi(shape="polygon", points=quad_pts + [(500.0, 300.0)], image_w=1280, image_h=720)
    poly_out = to_iwata_yaml_dict(poly_roi)
    all_ok &= check("polygon export uses 'calibrated_polygon' (not 'calibrated_quad')",
                     "calibrated_polygon" in poly_out and "calibrated_quad" not in poly_out)
    all_ok &= check("polygon export keeps all N points", len(poly_out["calibrated_polygon"]) == 5)

    generic = to_generic_json_dict(quad_roi)
    all_ok &= check("generic export normalizes points into 0..1",
                     all(0 <= x <= 1 and 0 <= y <= 1 for x, y in generic["points"]))
    all_ok &= check("generic export records image_size", generic["image_size"] == [1280, 720])

    print()
    print("ALL PASS" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
