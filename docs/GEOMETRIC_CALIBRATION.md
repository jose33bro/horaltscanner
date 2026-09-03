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

After intrinsics, the fixed Pi camera is the primary observable for the shared
mechanism model. Its PnP poses determine the signed X scale and the signed Y
command rotation within the measured 200 mm diameter tolerance. The service
then solves the Pi extrinsic before independently solving and cross-validating
the opposed USB camera against that global scanner-frame model. The USB
camera's commanded Z displacement is removed before fitting its reference
transform. Each USB view evaluates the four proper centered-board adjustments
(identity and 180° about board X, Y, or normal) against a robust rotation
consensus. This normalizes a detector/PnP correspondence-order switch in one
view without allowing a reflection or hiding continuous camera wobble. The
selected global convention and every per-view adjustment/residual are reported.
The fixed Pi observation still defines the canonical board convention; raw
camera-coordinate rotation signs are not compared across cameras.

The USB carriage coefficient is estimated after the fixed Pi-derived signed X
and Y mechanism transform has been applied. The estimator residualizes
commanded Z against commanded X/Y before solving the Z coefficient, so
correlated commands cannot silently remove its independent leverage. It keeps
all views whose joint translation RMS is within the unchanged 5 mm extrinsic
limit. Gross translation rejection is deterministic and may remove a view only
when another inlier remains at that same Z level. A PnP mask that removes a
whole Z level fails instead of triggering a biased refit. Calibration also
requires three Z levels spanning 20 mm, independent-Z leverage ratio at least
0.25, condition number at most 50, per-level repeatability at most 5 mm, and
leave-one-view/leave-one-level carriage-vector deviation at most 0.15 mm per
commanded mm. Reports include those values, per-level sample/inlier counts,
rejected views, and any direct same-X/same-Y Z contrasts.

The locally validated 11-pose trajectory has independent-Z leverage ratio
approximately 0.874, and the tracked seven-pose fallback is approximately
0.767, so neither needs a motion change for this estimator. A configured
trajectory whose Z is explained by X/Y is rejected before motion begins. A bad
USB fit, ambiguous board convention, out-of-tolerance scale, insufficient axis
travel or Z support, or excessive robust residuals fails calibration; motor
`rotation_distance` is never changed. The fitted signed Y scale is persisted
and used to undo turntable motion during scans. For every scan frame, runtime derives
the physical turntable center as
`reference_center + signed_x_scale * (current_x - reference_x) * scanner_+X`,
undoes Y rotation about that current center, then maps the result to the
trajectory-origin X center. This prevents pivot warp when automatic centering
moves X from 195 mm to 97.5 mm and also keeps future per-frame X trajectory
changes registered. Missing or inconsistent signed-X/reference metadata blocks
physical scans.

The moving USB fit preserves its complete signed carriage vector rather than
reducing it to a nominal Z direction. On the measured machine the live fit was
approximately `[-0.0117, -0.1742, -0.9370]` mm per commanded Z millimeter
(magnitude `0.953`, vertical alignment `10.557°`). The default vertical
alignment acceptance limit is therefore a measured-machine tolerance of
**12°**; the near-unit scale, regression observability/condition, 5 mm
translation residual, and 3° rotation residual checks remain unchanged.
The captured 35.04° failure contained discrete USB PnP convention switches at
views 8 and 9. Offline normalization recovered
`[-0.0150, -0.1853, -0.9251]`, magnitude about `0.944`, vertical alignment
about `11.36°`, and USB extrinsic residuals about `2.65 mm / 0.53°` with all
11 views. Thus that run was a fit artifact only after the corrected residuals
passed every unchanged safety limit; a normalized result that remains near
35° is still rejected.
TF-Luna is mounted to the same carriage. Its expected calibration readings and
persisted runtime correction use that validated signed USB vector exactly once.

Laser-plane calibration reuses the accepted checkerboard corners for each exact
camera/pose pair. Matched laser-minus-ambient red and chromatic response is
considered only inside an eroded inner-corner polygon, and ambient saturated
spots are excluded. The matched response is reflectance-normalized from the
ambient frame so black/white transitions do not become laser peaks. Bounded
horizontal Gaussian background estimates then remove smooth low-frequency pink
illumination and require a second, finer-scale sharpness response before row
peaks are measured. Each remaining peak needs bilateral local red/chromatic
prominence; its subpixel center and width are measured at half prominence. Rows
with comparable separated peaks are marked
ambiguous rather than allowing the line fit to choose one. A camera/laser
observation is accepted only when the resulting peaks form one thin, continuous
line with sufficient span and low image-line residual. A robust row fit may
discard isolated outlier rows or one short outlier segment. The strict unexplained
gap limit remains unchanged; only a low-response interval bounded by consecutive
perspective-projected checker rows may be bridged, and only up to 1.25 local
checker-square pitches with coherent endpoints and multiple sufficiently long
observed segments. Broad glow without an embedded narrow ridge, non-checker
gaps, two-square gaps, segment jumps, checker brightness changes, competing
ridges, reflections, and edge-only hits are recorded and skipped. Compact
per-view diagnostics report raw and unexplained maximum gaps, bridged checker
gaps, projected pitch/limit aggregates, segment/outlier counts, raw candidate
pixels, background-suppressed candidates, peak prominence, ambiguous rows, and
local width percentiles; images and per-row arrays are not embedded. Reflections
on the wall, platform, mount, or laser housing are never intersected with the
board plane. Because both laser modules are physically on the Pi Camera V3 NoIR
side, each laser plane is fitted only from valid Pi-camera on-board lines. USB
observations retain the same strict diagnostics and, when
they independently satisfy all point/view/orientation requirements, cross-check
the Pi plane without contributing samples to it. Each laser must still provide
at least the configured number of Pi points across three valid poses and three
independently oriented board views before the robust plane fit, and both the
plane RMS and optional USB cross-validation RMS limits remain **2 mm**. Laser
ambient and laser-on frames are captured under one Pi Camera photometric setting
per pose. With both lasers off, automatic exposure, analogue gain, and white
balance settle for `laser_photometric_settle_s` (default **1 second**); their
effective public Picamera2 metadata values are then locked and confirmed before
the ambient and both laser frames. Every exact image request must report matching
`ExposureTime`, `AnalogueGain`, and two-channel `ColourGains`; missing or drifting
numeric metadata rejects the observation. `AwbEnable` is also rejected when it
is reported as true, but Raspberry Pi OS libcamera stacks that omit this
input-state field are accepted only when the required colour gains remain
present and numerically locked across all frames. Failures list the relevant
metadata keys and values returned by the camera. The prior automatic/manual
controls are restored in a `finally` guard on success, failure, or cancellation. Missing Pi
controls fail preflight before laser-plane acquisition. A USB camera participates
in the optional laser cross-check only when a verified matched-photometry capture
path exists. The current OpenCV USB driver does not provide a portable exposure
lock, so the report records that diagnostic and the Pi-authoritative fit
continues. Laser
control remains binary at the API boundary, but the tracked production hardware
configuration opts GPIO27 and GPIO22 into 1 kHz `PWMOutputDevice` control at a
conservative 20% calibration duty. The calibration service selects that fixed,
bounded profile internally; callers cannot submit an arbitrary duty cycle.
Configurations without `lasers.pwm_enabled: true` retain the previous digital
full-power behavior for backward compatibility. Do not weaken the line width,
point, pose, orientation, spread, or 2 mm plane-fit gates to compensate for
optical saturation.

Calibration payload validation requires this Pi-authoritative provenance and
its surviving robust-fit per-pose point counts, view/orientation counts, and
two-dimensional spread condition. A pose that retains fewer than the configured
points after robust rejection is removed before the plane is refitted. A legacy
laser plane without that evidence is intentionally rejected and must be
recalibrated; it is not silently trusted after upgrade. Persistence prepares
the report and rollback backup, renames them, and syncs the parent directory
before atomically switching the active calibration file and syncing the
directory again. Runtime installation is part of the same non-cancellable
transaction; an installation failure restores both the complete previous disk
generation and runtime calibration. Cancellation is checked immediately before
this transaction and a later request waits for activation rather than reporting
a false cancelled outcome.
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

### Deploy the carriage-fit correction without replacing local configuration

After this correction is merged to `main`, preserve the Pi's locally tuned
11-pose trajectory, 5% PWM profile, scan poses, and hardware configuration.
The only intentional local setting change below restores the temporary USB
vertical-alignment override from 15° to the production 12° gate. These commands
do not move an axis or energize a laser:

```bash
set -eu
cd /home/pi/horaltscanner
test "$(git branch --show-current)" = main
sudo systemctl stop horalscanner
backup="$HOME/horalscanner-usb-fit-update-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup/config"
cp -a config/horalscanner.json config/horalscanner_config.json \
  config/scan_poses.json "$backup/config/"
if sudo test -e /var/lib/horalscanner/calibration.json; then
  sudo cp -a /var/lib/horalscanner/calibration.json "$backup/"
fi
git fetch origin main
git restore --source=HEAD --worktree -- \
  config/horalscanner.json config/horalscanner_config.json config/scan_poses.json
git merge --ff-only origin/main
cp -a "$backup/config/horalscanner.json" config/horalscanner.json
cp -a "$backup/config/horalscanner_config.json" config/horalscanner_config.json
cp -a "$backup/config/scan_poses.json" config/scan_poses.json

/home/pi/horaltscanner_env/bin/python - <<PY
import copy
import json
from pathlib import Path

backup = Path("$backup/config")
application_path = Path("config/horalscanner.json")
hardware_path = Path("config/horalscanner_config.json")
before = json.loads((backup / "horalscanner.json").read_text())
application = copy.deepcopy(before)
geometric = application["scanner"]["geometric_calibration"]
geometric["maximum_usb_z_vertical_alignment_deg"] = 12
geometric["minimum_carriage_z_leverage_ratio"] = 0.25
geometric["maximum_usb_z_vector_uncertainty_mm_per_commanded_mm"] = 0.15
application_path.write_text(json.dumps(application, indent=2) + "\n")

start = geometric["starting_pose_mm"]
poses = [
    {
        axis: float(start[axis]) + float(offset.get(axis, 0))
        for axis in ("x", "y", "z")
    }
    for offset in geometric["pose_offsets_mm"]
]
assert len(poses) == 11, f"expected preserved 11-pose trajectory, got {len(poses)}"
assert poses[0] == {"x": 195.0, "y": 0.0, "z": 20.0}
assert all(0.0 <= pose["x"] <= 195.0 for pose in poses)
assert all(20.0 <= pose["z"] <= 40.0 for pose in poses)
assert geometric["usb_z_scale_tolerance_fraction"] == 0.15
assert geometric["maximum_usb_z_vertical_alignment_deg"] == 12
assert geometric["maximum_carriage_fit_condition_number"] == 50
assert geometric["maximum_extrinsic_rms_mm"] == 5
assert geometric["maximum_extrinsic_rms_deg"] == 3
assert geometric["maximum_laser_plane_rms_mm"] == 2

preserved = copy.deepcopy(application)
preserved_geometric = preserved["scanner"]["geometric_calibration"]
original = copy.deepcopy(before)
original_geometric = original["scanner"]["geometric_calibration"]
for key in (
    "maximum_usb_z_vertical_alignment_deg",
    "minimum_carriage_z_leverage_ratio",
    "maximum_usb_z_vector_uncertainty_mm_per_commanded_mm",
):
    preserved_geometric.pop(key, None)
    original_geometric.pop(key, None)
assert preserved == original, "an unrelated application setting changed"

hardware = json.loads(hardware_path.read_text())
assert hardware["lasers"]["pwm_enabled"] is True
assert hardware["lasers"]["calibration_power"] == 0.05
PY

cmp "$backup/config/horalscanner_config.json" config/horalscanner_config.json
cmp "$backup/config/scan_poses.json" config/scan_poses.json
/home/pi/horaltscanner_env/bin/python -m py_compile \
  software/api/geometric_calibration.py
/home/pi/horaltscanner_env/bin/python -m pytest -q software/tests
sudo test ! -e /var/lib/horalscanner/calibration.json
sudo systemctl restart horalscanner
sudo systemctl status --no-pager horalscanner
curl -fsS http://127.0.0.1:5000/api/status | python3 -m json.tool
```

The final `sudo test` is expected for the stated no-calibration-file starting
state. If a supervised run has since created a calibration, replace it with
`sudo python3 -m json.tool /var/lib/horalscanner/calibration.json >/dev/null`;
never delete a measured calibration as part of deployment.

Keep the exact measured TF-Luna origin/direction and start pose in
`/home/pi/geometric-calibration-request.locked-5pct.json`; do not remeasure or
substitute placeholders during this software-only retest. With the board and
support rigid, USB cable free, lasers confirmed off, the travel envelope clear,
an accessible emergency stop, and an operator present, home X/Y/Z and confirm
X=195, Y=0, Z=20 before repeating the same request:

```bash
request=/home/pi/geometric-calibration-request.locked-5pct.json
python3 -m json.tool "$request" >/dev/null
curl -fsS -X POST -H 'Content-Type: application/json' \
  --data-binary @"$request" \
  http://127.0.0.1:5000/api/calibration/geometric/preflight |
  python3 -m json.tool
curl -fsS -X POST -H 'Content-Type: application/json' \
  --data-binary @"$request" \
  http://127.0.0.1:5000/api/calibration/geometric/start |
  python3 -m json.tool
watch -n 1 'curl -fsS http://127.0.0.1:5000/api/calibration/geometric/status'
curl -fsS \
  'http://127.0.0.1:5000/api/calibration/geometric/report?download=1' \
  -o horalscanner-calibration-report-usb-fit-1.json
```

For an accepted run, verify `carriage_fit` reports all five local Z levels,
independent-Z leverage at least 0.25, vector uncertainty at most 0.15,
scale within 15%, vertical alignment at most 12°, and USB extrinsics within
5 mm / 3°. A `changed_views` list is acceptable only when the normalized
per-view rotation residuals and final extrinsic gates pass. Do not raise any
limit for a failure.

With the setup unchanged and still supervised, run the same request once more
and save `horalscanner-calibration-report-usb-fit-2.json`. Compare the two
carriage vectors, per-Z-level repeatability, normalized PnP adjustments, and
extrinsic residuals. Stop and retain both reports if a level disappears, the
adjustments oscillate without a discrete 180° correspondence switch, the
vector remains near 35°, or either run fails an existing gate.

Do not create or copy a calibration file after a failed run. The service writes
runtime calibration only after every existing point, pose, orientation, spread,
ray, residual, and 2 mm plane-fit gate succeeds.

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
