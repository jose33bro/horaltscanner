# Manual Tests

Practical, copy/paste manual verification steps for HoralScanner hardware
endpoints, to be run directly on the Raspberry Pi against a running
`software/api/horalscanner_api.py` instance (default `http://127.0.0.1:5000`).

See `API_CONTRACT.md` for the exact payload contracts referenced below.

## Fans (0.0, 0.5, 1.0)

```bash
for s in 0.0 0.5 1.0; do
  echo "== speed=$s =="
  curl -sS -X POST http://127.0.0.1:5000/api/fan/creality \
    -H "Content-Type: application/json" -d "{\"speed\": $s}"; echo
  curl -sS -X POST http://127.0.0.1:5000/api/fan/temperature \
    -H "Content-Type: application/json" -d "{\"speed\": $s}"; echo
done
curl -sS http://127.0.0.1:5000/api/fan/status; echo
```

Expected: every call returns `200` with `"success": true`; `/api/fan/status`
reflects the last speed set for each fan.

Rejected payloads (should return `400`):

```bash
curl -i -sS -X POST http://127.0.0.1:5000/api/fan/creality \
  -H "Content-Type: application/json" -d '{"enabled": true}'
curl -i -sS -X POST http://127.0.0.1:5000/api/fan/creality \
  -H "Content-Type: application/json" -d '{"speed": 255}'
```

## Lasers on/off

```bash
curl -sS -X POST http://127.0.0.1:5000/api/laser/left  -H "Content-Type: application/json" -d '{"state": true}'; echo
curl -sS -X POST http://127.0.0.1:5000/api/laser/right -H "Content-Type: application/json" -d '{"state": true}'; echo
curl -sS -X POST http://127.0.0.1:5000/api/laser/left  -H "Content-Type: application/json" -d '{"state": false}'; echo
curl -sS -X POST http://127.0.0.1:5000/api/laser/right -H "Content-Type: application/json" -d '{"state": false}'; echo
curl -sS http://127.0.0.1:5000/api/laser/status; echo
```

Expected: each response includes `"status": {"left": ..., "right": ...}`
matching the requested state.

## RGB colors

```bash
curl -sS -X POST http://127.0.0.1:5000/api/led/color -H "Content-Type: application/json" -d '{"r":255,"g":0,"b":0}'; echo
curl -sS -X POST http://127.0.0.1:5000/api/led/color -H "Content-Type: application/json" -d '{"r":0,"g":255,"b":0}'; echo
curl -sS -X POST http://127.0.0.1:5000/api/led/color -H "Content-Type: application/json" -d '{"r":0,"g":0,"b":255}'; echo
curl -sS -X POST http://127.0.0.1:5000/api/led/color -H "Content-Type: application/json" -d '{"r":0,"g":0,"b":0}'; echo
```

Expected: LED visibly changes color, response echoes the requested
`{"r","g","b"}` values.

## USB camera status/frame

```bash
# List detected V4L2 devices to know which index is real hardware
ls -l /dev/video*
v4l2-ctl --list-devices 2>/dev/null || true

# Raw OpenCV probe (useful to cross-check backend fallback behaviour)
python3 - <<'PY'
import cv2
for i in [0, 1, 2, 3]:
    cap = cv2.VideoCapture(i)
    ok, frame = cap.read()
    print(f"idx {i}: opened={cap.isOpened()} read={ok} shape={None if not ok else frame.shape}")
    cap.release()
PY

# Backend endpoints
curl -sS http://127.0.0.1:5000/api/camera/usb/status; echo
curl -I -sS "http://127.0.0.1:5000/api/camera/usb/frame?t=$(date +%s)"
```

Expected:
- `available: true` in the status response as soon as the hardware is
  readable on *any* of the fallback indices (`0,1,2,3`), even if the
  configured index in `hardware.json`/`camera_config` is wrong.
- `/api/camera/usb/frame` returns HTTP `200` with an `image/jpeg` body.
- Application logs (`journalctl -u horalscanner -n 80 --no-pager` or stdout)
  show a line such as `USB camera: configured device_id=2 failed, falling
  back to working index 0` when a fallback occurred.

## Calibration fallback note

Auto-calibration (`POST /api/camera/calibrate/pose/<camera>` and related
`goto_calibration_pose` flow) can fail on some setups (e.g. LiDAR out of
tolerance, checkerboard not detected). If auto-calibration fails:

1. Use the manual jog controls in the web UI (`Workshop` tab) to move
   X/Y/Z until the target/checkerboard is centered in the camera frame.
2. Use `POST /api/camera/<camera>/save_scan_pose` to persist the manually
   found pose instead of relying on the automatic calibration routine.
3. Re-run `GET /api/camera/<camera>/status` and `.../frame` to confirm the
   camera still reports available/streaming correctly after the manual
   adjustment.
