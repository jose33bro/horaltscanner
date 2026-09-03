# Supervised geometric calibration

The geometric wizard calibrates the physical scanner without manufacturing
missing geometry. A real scan remains blocked until every result and its
quality evidence has been accepted.

## Measured fixture and scanner frame

- Checkerboard: **11 × 6 inner corners** (12 × 7 squares), **13 mm** square size.
- The checkerboard center is placed on the center of the measured **200 mm
  diameter** turntable.
- The circumference is derived and recorded as `pi * 200 =
  628.318530717... mm`; the workflow does not silently change any motor
  `rotation_distance`.
- Frame origin: checkerboard/turntable center at the reference pose.
- +X: checkerboard normal at the Y reference; +Y: checkerboard horizontal
  direction/turntable tangent at Y=0; +Z: checkerboard vertical direction and
  turntable axis, upward. The signs relating commanded X and Y to this physical
  frame are estimated from PnP observations, not assumed.

The configured X=195, Y=0, Z=20 mm pose keeps a temporary 5 mm margin from the
first observed mechanical contact at X=200 while preserving the camera framing.
The calibration service hard-caps every trajectory pose at X=195 mm even if an
unsafe higher limit is supplied, and caps calibration Z at the validated 40 mm.
The default seven poses are:

| View | X (mm) | Y travel (mm / degrees) | Z (mm) |
|---:|---:|---:|---:|
| 1 | 195 | 0 / 0° | 20 |
| 2 | 185 | 10.4719755 / 6° | 30 |
| 3 | 175 | 20.9439510 / 12° | 40 |
| 4 | 165 | 31.4159265 / 18° | 20 |
| 5 | 195 | 41.8879020 / 24° | 40 |
| 6 | 165 | 52.3598776 / 30° | 30 |
| 7 | 180 | 62.8318531 / 36° | 40 |

Because the checkerboard is centered, a stable Pi-camera checkerboard center is
expected. Diversity is measured from normalized corresponding-corner motion,
centered shape change, scale, orientation, per-corner motion hulls, and unique
views. Center movement is diagnostic only. Status and reports include every
metric and threshold.

After intrinsics, the service fits a shared mechanism model from both cameras'
PnP poses. It evaluates both Y rotation directions and estimates signed radians
per commanded millimeter within the measured 200 mm diameter tolerance. It then
robustly regresses signed X millimeters per commanded millimeter. The USB
camera's commanded Z displacement is removed before fitting its reference
transform. Ambiguous directions, an out-of-tolerance scale, insufficient axis
travel, or excessive robust residuals fail calibration; motor
`rotation_distance` is never changed. The fitted signed Y scale is persisted and
used to undo turntable motion during scans. For every scan frame, runtime derives
the physical turntable center as
`reference_center + signed_x_scale * (current_x - reference_x) * scanner_+X`,
undoes Y rotation about that current center, then maps the result to the
trajectory-origin X center. This prevents pivot warp when automatic centering
moves X from 195 mm to 97.5 mm and also keeps future per-frame X trajectory
changes registered. Missing or inconsistent signed-X/reference metadata blocks
physical scans.
The workflow suspends TF-Luna ranging output once before checkerboard camera
capture, waits for the optical spot to clear, and restores ranging output in a
`finally` guard before any LiDAR measurements. Cancellation and failure paths
also restore output. The workflow rejects the pose if both cameras do not detect
a fresh checkerboard view with at least the configured 2% inner-corner frame
margin and 3% image coverage.
Calibration accepts only the configured 11 × 6 pattern;
a 10 × 6 subset detection is explicitly rejected.
Detection first uses the fast classic OpenCV detector, which normally detects
this board despite the TF-Luna spot. The sector-based detector is only a
bounded fallback. Each bounded attempt also tries histogram equalization before
the sector-based detector, which recovers the low-contrast Logitech C270 view.
If these fail, one small saturated blue IR blob may be masked and inpainted
before a final retry; broad white board regions are never masked. This only
protects corner detection—the IR spot is not used as geometric evidence. Any
result whose glare mask overlaps a detected corner remains rejected. Framing
failures report the measured edge margin or coverage separately from detector
failures. The workflow does not require the absent RGB LED.
Calibration allows up to 8 seconds for each ARM checkerboard attempt and
retries up to three fresh frames, accepting the first exact 11 × 6 result.
Both cameras share a bounded 35-second framing deadline at each pose; a single
timed-out frame does not abort the run, and cancellation is checked while
OpenCV detection is pending. Normal camera API deadlines are unchanged.

## Before supervised motion

Deploy in a single hardware-owning process. With the API stopped, update the
checkout, install existing dependencies, validate syntax/tests, and restart:

```bash
cd /opt/horalscanner
git fetch origin
git checkout main
git pull --ff-only origin main
python3 -m pip install -r requirements.txt
python3 -m py_compile software/api/checkerboard_detector.py \
  software/api/geometric_calibration.py software/api/lidar_driver.py
sudo systemctl restart horalscanner
sudo systemctl status --no-pager horalscanner
```

These checks do not command motion or energize a laser:

```bash
curl -fsS http://127.0.0.1:5000/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:5000/api/calibration/geometric/status | python3 -m json.tool
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"start_pose":{"x":195,"y":0,"z":20},"lidar_measurements":{"origin_mm":[MEASURE_X,MEASURE_Y,MEASURE_Z],"direction":[DIR_X,DIR_Y,DIR_Z],"reference_z_mm":20}}' \
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
  -d '{"start_pose":{"x":195,"y":0,"z":20},"lidar_measurements":{"origin_mm":[MEASURE_X,MEASURE_Y,MEASURE_Z],"direction":[DIR_X,DIR_Y,DIR_Z],"reference_z_mm":20}}' \
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
On failure, `status` and the downloadable in-memory report include only compact
per-view commanded poses, PnP board centers/rotation vectors, diversity
statistics, signed-axis candidate scores, and transform residuals. Camera images
are not embedded.

## Durable state and OS upgrades

Measured calibration is stored outside the git checkout at
`/var/lib/horalscanner/calibration.json`. It is loaded as a validated overlay
over tracked hardware defaults, so `git pull`, reinstall, and OS repair cannot
replace it. The systemd service sets `HORALSCANNER_CALIBRATION_STATE` and
creates the state directory for user `pi`. A valid legacy calibration embedded
in the tracked hardware config is migrated only when no runtime file exists.
Existing runtime state is never overwritten by migration.

After a Raspberry Pi OS 64-bit Lite upgrade, run the idempotent repair mode:

```bash
cd /home/pi/horaltscanner
sudo bash setup_pi.sh --repair
curl -fsS http://127.0.0.1:5000/api/status | python3 -m json.tool
```

This rechecks rpicam/libcamera, Picamera2, OpenCV, Python requirements, groups,
udev aliases, and systemd. Its health checks do not move an axis or energize a
laser. Repair first verifies `import libcamera` with `/usr/bin/python3`, then
creates or upgrades `/home/pi/horaltscanner_env` with
`--system-site-packages`. A venv whose interpreter cannot execute is recreated
at that resolved venv path only. It validates all required imports before
changing or restarting the systemd unit; on validation failure the currently
running service and unit are left untouched.
After restart, the non-motion health check polls systemd and `GET /api/status`
every two seconds for up to 45 seconds, allowing Flask and the camera stack to
finish startup before reporting a real timeout.

Back up runtime state before an OS reinstall:

```bash
sudo systemctl stop horalscanner
sudo tar -C /var/lib/horalscanner -czf "$HOME/horalscanner-calibration.tgz" \
  calibration.json*
sudo systemctl start horalscanner
```

Restore it atomically after setup:

```bash
mkdir -p "$HOME/horalscanner-calibration-restore"
tar -C "$HOME/horalscanner-calibration-restore" -xzf "$HOME/horalscanner-calibration.tgz"
python3 -m json.tool "$HOME/horalscanner-calibration-restore/calibration.json" >/dev/null
sudo install -o pi -g pi -m 0640 \
  "$HOME/horalscanner-calibration-restore/calibration.json" \
  /var/lib/horalscanner/calibration.json.new
sudo mv /var/lib/horalscanner/calibration.json.new /var/lib/horalscanner/calibration.json
sudo systemctl restart horalscanner
```

Never copy the tracked `config/horalscanner_config.json` calibration placeholders
over this measured runtime file. Moving USB-camera and TF-Luna transforms are
anchored to their persisted `reference_axis_position_mm`; scan preflight rejects
missing, non-finite, or out-of-limit references.
