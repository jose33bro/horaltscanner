# Real scan acquisition

Real acquisition is enabled only when `scanner.mode` is `real` (with the legacy
`scanner.simulation` flag set consistently to `false`). It never falls back to
synthetic points. A physical scan requires connected hardware,
all axes homed, a saved scan pose, explicit trajectory limits, and complete
camera, laser-plane, turntable, and TF-Luna calibration in
`config/horalscanner_config.json`.

The default trajectory is deliberately limited to three Y positions and two Z
levels (10 mm Y travel and 5 mm Z travel). At each pose it:

1. samples the TF-Luna;
2. captures ambient frames from the Pi Camera and Logitech C270;
3. turns on one laser at a time and captures both cameras;
4. forces that laser off before selecting the other side;
5. extracts the red laser displacement and intersects calibrated camera rays
   with the calibrated laser plane;
6. transforms points into the scanner frame and compensates turntable motion.

Cancellation and acquisition failures force both lasers off and issue
`STOP ALL`. A successful bounded scan restores its starting scan pose.
Run the API as exactly one OS process; multiple Gunicorn workers would compete
for GPIO, serial ports, cameras, and independent in-memory scan state.

## Calibration contract

Replace every `null` in `scan_calibration` with measured values:

- each camera needs a 3x3 `intrinsic_matrix` and 4x4
  `camera_to_scanner` transform;
- each laser needs a scanner-frame plane `normal` and `offset_mm`, using
  `normal dot point + offset_mm = 0`;
- the turntable needs `center_mm`, unit `axis`, and measured
  `mm_per_revolution`;
- the TF-Luna needs a 4x4 `lidar_to_scanner` transform and validated distance
  range.

Preflight rejects singular, non-finite, zero-length, or incomplete calibration.
Do not enter estimated values merely to bypass the gate.

## Deployment and non-motion checks

```bash
git fetch origin
git checkout jose33bro-real-hardware-scanning
git pull --ff-only
python3 -m pip install -r requirements.txt
sudo systemctl restart horalscanner
sudo systemctl status horalscanner --no-pager

curl -fsS http://127.0.0.1:5000/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:5000/api/scan/preflight | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:5000/api/scan/preflight | python3 -m json.tool
```

`GET /api/scan/preflight` is passive. `POST /api/scan/preflight` opens and
captures both cameras, reads TF-Luna, and forces both lasers off; it does not
turn lasers on or move motors.

## Supervised movement and scan

Wear laser eye protection, clear the travel envelope, keep emergency power
cutoff accessible, and supervise these commands locally:

```bash
# Physical movement: home all axes and wait for homing completion.
curl -fsS -X POST http://127.0.0.1:5000/api/home/all | python3 -m json.tool
curl -fsS http://127.0.0.1:5000/api/motor/status | python3 -m json.tool

# After positioning and validating the intended reference pose, persist it.
curl -fsS -X POST http://127.0.0.1:5000/api/scan/pose/save \
  -H 'Content-Type: application/json' \
  -d '{"camera":"pi"}' | python3 -m json.tool

# Must report ready=true and an empty blockers list before starting.
curl -fsS -X POST http://127.0.0.1:5000/api/scan/preflight | python3 -m json.tool

# Physical movement, lasers, cameras, and LiDAR are active after this request.
curl -fsS -X POST http://127.0.0.1:5000/api/scan/start | python3 -m json.tool
watch -n 1 'curl -fsS http://127.0.0.1:5000/api/scan/status | python3 -m json.tool'

# Emergency/cancel path.
curl -fsS -X POST http://127.0.0.1:5000/api/scan/stop | python3 -m json.tool
curl -fsS -X POST http://127.0.0.1:5000/api/motor/stop \
  -H 'Content-Type: application/json' -d '{"axis":"all"}' | python3 -m json.tool
```

## Tests

```bash
python3 -m pytest \
  software/tests/test_scanner_engine.py \
  software/tests/test_horalscanner_api.py \
  software/tests/test_scan_blueprint.py \
  software/tests/test_stm32_driver.py -q
python3 -m pytest software/tests -q
```
