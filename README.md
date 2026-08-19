# Cam Bench

Standalone desktop tool to see a camera's live feed, tune exposure/gain/white
balance/etc, mark and export an ROI, and record video - for any camera type
(V4L2/UVC, OPT USB3 Vision, and GigE Vision as a future stub), auto-detected.

## What it does

Use the app during camera setup and image-capture work in any project: inspect
the live feed, tune exposure and other camera controls, trace an ROI, export
its geometry, save reference frames, and record video clips without writing
project-specific tooling.

## Run

```
pip install -r requirements.txt
python -m cam_bench.app
```

For an OPT (USB3 Vision) camera, set `CAM_BENCH_OPT_PYTHON` to the Python
interpreter that has the vendor `optcam` SDK installed (it's a compiled wheel
tied to one Python version, so it runs in its own process - see
`cam_bench/backends/opt.py`):

```
export CAM_BENCH_OPT_PYTHON=/path/to/optcam-venv/bin/python
```

The app is a viewer, not a configurator: it reads back the OPT camera's trigger
mode, auto-exposure/gain flags, exposure, gain and buffer count before touching
them, and writes them back when the camera is closed. Those are volatile
registers that survive process exit and only reset on a power cycle, so without
that a tuning session here would silently reconfigure the next project to open
the same camera.

## Architecture

- `cam_bench/backends/` - `CameraBackend` ABC (`base.py`) + one subclass per
  camera type (`v4l2.py`, `opt.py`, `gige.py` stub). The UI/server never
  branch on camera type, only on this interface.
- `cam_bench/imaging.py` - focus score (Laplacian variance), histogram,
  exposure-clipping (zebra) overlay.
- `cam_bench/roi.py` - ROI model plus generic JSON and YAML export formats for
  reusing regions of interest in downstream camera and image-processing tools.
- `cam_bench/recorder.py` - `cv2.VideoWriter` wrapper.
- `cam_bench/session.py` - state shared between the JS bridge and the HTTP
  server (the one active backend, ROI points, recorder, ...).
- `cam_bench/server.py` - local HTTP server: serves the UI, a live JPEG
  endpoint, and a stats endpoint, off one background grab loop.
- `cam_bench/api.py` - pywebview `js_api` bridge the frontend calls into.
- `cam_bench/app.py` - entry point: starts the server, opens the pywebview
  window.
- `web/index.html` - the UI (plain HTML/CSS/JS, no build step).

## Tests

No hardware needed - offline checks use synthetic frames and a stub worker
process:

```
python tests/test_imaging.py
python tests/test_roi_export.py
python tests/test_opt_backend.py
python tests/test_server_routes.py
```

Real V4L2/OPT hardware needs a manual smoke check - discover a device, open
it, confirm a real frame comes back - there's no way to automate that without
the camera physically present.
