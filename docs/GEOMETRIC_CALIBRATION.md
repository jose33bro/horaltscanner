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
- +X: radial, positive with commanded X; +Y: turntable tangent at Y=0; +Z:
  turntable axis, upward.

The configured X=210, Y=0, Z=10 mm pose is the measured glare-free starting
candidate. The
workflow rejects it if both cameras do not detect a fresh, well-margined
checkerboard view. Calibration accepts only the configured 11 × 6 pattern;
a 10 × 6 subset detection is explicitly rejected.
Detection first uses the fast classic OpenCV detector, which normally detects
this board despite the TF-Luna spot. The sector-based detector is only a
bounded fallback. If both fail, one small saturated/chromatic IR blob may be
masked and inpainted before a final retry; broad white board regions are never
masked. This only protects corner detection—the IR spot is not used as
geometric evidence. The workflow does not require the absent RGB LED.
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
python3 -m py_compile software/api/geometric_calibration.py software/api/scanner_engine.py
sudo systemctl restart horalscanner
sudo systemctl status --no-pager horalscanner
```

These checks do not command motion or energize a laser:

```bash
curl -fsS http://127.0.0.1:5000/api/status | python3 -m json.tool
curl -fsS http://127.0.0.1:5000/api/calibration/geometric/status | python3 -m json.tool
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"start_pose":{"x":210,"y":0,"z":10},"lidar_measurements":{"origin_mm":[MEASURE_X,MEASURE_Y,MEASURE_Z],"direction":[DIR_X,DIR_Y,DIR_Z]}}' \
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
  -d '{"start_pose":{"x":210,"y":0,"z":10},"lidar_measurements":{"origin_mm":[MEASURE_X,MEASURE_Y,MEASURE_Z],"direction":[DIR_X,DIR_Y,DIR_Z]}}' \
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
