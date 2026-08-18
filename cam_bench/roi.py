"""ROI drawing model + export. The Iwata export format matches
lcd_inspection/roi.py + camera.py's load_camera_specs() field-for-field (fallback_rect /
calibrated_quad / calibrated_polygon + warp_size), so it drops into that project's
runtime_iwata.yaml directly instead of being hand-traced with trace_screen_polygon.py."""
from __future__ import annotations

from pydantic import BaseModel

Point = tuple[float, float]


class Roi(BaseModel):
    shape: str            # "rect" | "quad" | "polygon"
    points: list[Point]   # pixel coordinates in the source frame
    image_w: int
    image_h: int


def to_iwata_yaml_dict(roi: Roi) -> dict:
    if roi.shape == "rect":
        xs = [p[0] for p in roi.points]
        ys = [p[1] for p in roi.points]
        x0, y0 = min(xs), min(ys)
        return {"fallback_rect": {"x": int(x0), "y": int(y0),
                                   "w": int(max(xs) - x0), "h": int(max(ys) - y0)}}
    key = "calibrated_quad" if roi.shape == "quad" else "calibrated_polygon"
    return {
        key: [[round(x, 1), round(y, 1)] for x, y in roi.points],
        "warp_size": {"w": roi.image_w, "h": roi.image_h},
    }


def to_generic_json_dict(roi: Roi) -> dict:
    """Normalized (0-1) points, portable across cameras/resolutions for other projects."""
    return {
        "shape": roi.shape,
        "points": [[round(x / roi.image_w, 6), round(y / roi.image_h, 6)] for x, y in roi.points],
        "image_size": [roi.image_w, roi.image_h],
    }
