# Supervised geometric calibration

The geometric wizard calibrates the physical scanner without manufacturing
missing geometry. A real scan remains blocked until every result and its
quality evidence has been accepted.

## Measured fixture and scanner frame

- Checkerboard: **11 × 6 inner corners**, **13 mm** square size.
- The checkerboard center is placed on the center of the measured **200 mm
  diameter** turntable.
- The circumference is derived and recorded as `pi * 200 =
  628.318530717... mm`; the workflow does not silently change any motor
  `rotation_distance`.
- Frame origin: checkerboard/turntable center at the reference pose.
- +X: radial, positive with commanded X; +Y: turntable tangent at Y=0; +Z:
  turntable axis, upward.

The configured X=185, Y=0, Z=25 mm pose is only a starting candidate. The
workflow rejects it if both cameras do not detect a fresh, well-margined
checkerboard view. Detection tries the classic OpenCV detector and the more
robust sector-based detector on a bounded image while returning full-frame
corner coordinates. If both fail, one small saturated/chromatic IR blob may
be masked and inpainted before a final retry; broad white board regions are
never masked. This only protects corner detection—the IR spot is not used as
geometric evidence. The workflow does not require the absent RGB LED.

## Before supervised motion

Deploy in a single hardware-owning process. With the API stopped, update the
checkout, install existing dependencies, validate syntax/tests, and restart:

```bash
cd /opt/horalscanner
git fetch origin
git checkout main
git pull --ff-only origin main
python3 -m pip install -r requirements.txt
python3 -m py_compile software/api/geometric_calibration.py software/api/scanner_engine.py
sudo systemctl restart horalscanner
sudo systemctl status --no-pager horalscanner
```

These checks do not command motion or energize a laser:

```bash
curl -fsS http://127.0.0.1:5000/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:5000/api/calibration/geometric/status | python3 -m json.tool
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"start_pose":{"x":185,"y":0,"z":25},"lidar_measurements":{"origin_mm":[MEASURE_X,MEASURE_Y,MEASURE_Z],"direction":[DIR_X,DIR_Y,DIR_Z]}}' \
  http://127.0.0.1:5000/api/calibration/geometric/preflight | python3 -m json.tool
```

Replace every `MEASURE_*`/`DIR_*` token with independently measured TF-Luna
beam geometry in the scanner frame. Range readings alone cannot determine the
full transform.

## Supervised run

Home X/Y/Z using the existing controls first. Center and secure the board,
clear the full travel envelope, provide an accessible emergency stop, and
keep an operator present. Prefer the web wizard. The equivalent start request
is:

```bash
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"start_pose":{"x":185,"y":0,"z":25},"lidar_measurements":{"origin_mm":[MEASURE_X,MEASURE_Y,MEASURE_Z],"direction":[DIR_X,DIR_Y,DIR_Z]}}' \
  http://127.0.0.1:5000/api/calibration/geometric/start | python3 -m json.tool
watch -n 1 'curl -fsS http://127.0.0.1:5000/api/calibration/geometric/status'
```

Emergency software cancellation always requests a motor stop and both lasers
off:

```bash
curl -fsS -X POST http://127.0.0.1:5000/api/calibration/geometric/cancel
curl -fsS http://127.0.0.1:5000/api/calibration/geometric/report?download=1 \
  -o horalscanner-calibration-report.json
```

The service accepts and atomically installs calibration only after finite,
invertible transforms and all RMS/residual limits pass. The previous
configuration is retained for `/api/calibration/geometric/rollback`.
