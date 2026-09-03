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

## Laser PWM safety configuration

The public laser routes remain boolean ON/OFF controls. When ON, the GPIO driver
selects one of three administrator-configured profiles from
`config/horalscanner_config.json`: `default_power`, `calibration_power`, or
`scan_power`. Geometric calibration and real acquisition select their respective
profiles internally, so scan acquisition cannot silently return to 100%.

The tracked Raspberry Pi configuration enables both MOSFET-driven 5 V line
lasers at 1 kHz with a conservative 0.20 duty for all profiles and a configured
0.35 ceiling:

```json
{
  "lasers": {
    "pwm_enabled": true,
    "pwm_frequency_hz": 1000,
    "maximum_power": 0.35,
    "default_power": 0.20,
    "calibration_power": 0.20,
    "scan_power": 0.20
  }
}
```

Each power can be overridden under `lasers.left` or `lasers.right`, and each
side may set a lower `maximum_power`. Every configured duty must be finite,
greater than zero, and no greater than both its side and global maximum.
Frequency must be 1-100000 Hz. Invalid settings prevent driver construction
before GPIO is touched. Missing PWM fields preserve legacy digital
`OutputDevice` behavior; only an explicit `pwm_enabled: true` opts in.

Startup creates laser outputs with zero duty and explicitly drives both OFF.
ON/OFF, cancellation, reconnect, partial initialization failure, and close are
serialized; cleanup drives each laser OFF before releasing its device. The
existing `active_high` setting is passed unchanged to both digital and PWM
devices.

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
cd /home/pi/horaltscanner
sudo systemctl stop horalscanner
cp config/horalscanner.json /var/tmp/horalscanner-live-application.json
cp config/horalscanner_config.json /var/tmp/horalscanner-live-hardware.json
git stash push -m pre-laser-pwm-live-config -- \
  config/horalscanner.json config/horalscanner_config.json
git fetch origin
git checkout main
git pull --ff-only origin main

# Restore all machine-local settings, including the balanced paired 11-pose
# trajectory and calibration references, then opt only the lasers into PWM.
cp /var/tmp/horalscanner-live-application.json config/horalscanner.json
cp /var/tmp/horalscanner-live-hardware.json config/horalscanner_config.json
python3 - <<'PY'
import json
from pathlib import Path

application_path = Path("config/horalscanner.json")
hardware_path = Path("config/horalscanner_config.json")
application = json.loads(application_path.read_text())
hardware = json.loads(hardware_path.read_text())
poses = application["scanner"]["geometric_calibration"]["pose_offsets_mm"]
assert len(poses) == 11, f"expected preserved 11-pose trajectory, got {len(poses)}"
assert application["scanner"]["geometric_calibration"]["starting_pose_mm"]["x"] == 195
assert application["scanner"]["geometric_calibration"]["maximum_laser_plane_rms_mm"] == 2
assert hardware["lasers"]["left"]["gpio"] == 27
assert hardware["lasers"]["right"]["gpio"] == 22
hardware["lasers"].update({
    "pwm_enabled": True,
    "pwm_frequency_hz": 1000,
    "maximum_power": 0.35,
    "default_power": 0.20,
    "calibration_power": 0.20,
    "scan_power": 0.20,
})
hardware_path.write_text(json.dumps(hardware, indent=2) + "\n")
print("preserved 11 poses, X195, 2 mm RMS gate, GPIO27/22; enabled 20% PWM")
PY

python3 -m pip install -r requirements.txt
PYTHONPATH="$PWD:$PWD/software" python3 - <<'PY'
import json
from software.drivers.gpio_driver import GPIODriver

with open("config/horalscanner_config.json") as handle:
    config = json.load(handle)
driver = GPIODriver(simulation=True, hardware_config=config)
assert driver.status()["laser_drive"] == "pwm"
print("PWM configuration validated without touching GPIO")
PY
sudo systemctl restart horalscanner
sudo systemctl status --no-pager horalscanner

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
# Re-run geometric calibration first with the same independently measured
# request and the balanced paired 11-pose trajectory.
python3 -m json.tool "$HOME/calibration-request.json" >/dev/null
curl -fsS -X POST -H 'Content-Type: application/json' \
  --data-binary @"$HOME/calibration-request.json" \
  http://127.0.0.1:5000/api/calibration/geometric/preflight \
  | tee /tmp/geometric-preflight.json | python3 -m json.tool

# Continue only when ready=true. This energizes lasers at calibration_power.
curl -fsS -X POST -H 'Content-Type: application/json' \
  --data-binary @"$HOME/calibration-request.json" \
  http://127.0.0.1:5000/api/calibration/geometric/start | python3 -m json.tool
watch -n 1 'curl -fsS http://127.0.0.1:5000/api/calibration/geometric/status | python3 -m json.tool'
curl -fsS 'http://127.0.0.1:5000/api/calibration/geometric/report?download=1' \
  -o "$HOME/horalscanner-calibration-pwm.json"

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
curl -fsS -X POST http://127.0.0.1:5000/api/calibration/geometric/cancel | python3 -m json.tool
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
