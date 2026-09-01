# API Contract

Confirmed request/response payloads for the HoralScanner REST API
(`software/api/horalscanner_api.py`), validated on live Raspberry Pi hardware.

## Fans

`POST /api/fan/creality`
`POST /api/fan/temperature`
`POST /api/fan/pi`

Accepted payload (exactly one of the following keys):

| Key       | Type  | Range      | Notes                                   |
|-----------|-------|------------|------------------------------------------|
| `speed`   | float | `0.0`-`1.0`| Preferred, PWM duty cycle.                |
| `pwm`     | float | `0.0`-`1.0`| Alias for `speed`.                        |
| `percent` | float | `0`-`100`  | Converted internally to `speed / 100.0`.  |

Example:

```bash
curl -X POST http://127.0.0.1:5000/api/fan/creality \
  -H "Content-Type: application/json" \
  -d '{"speed": 0.5}'
```

`{"enabled": true}` and raw integers in the `0..255` range are **not**
accepted and return `400 Invalid fan speed value` (missing/out-of-range key).

`GET /api/fan/status` returns the current speed of every fan.

## Lasers

`POST /api/laser/<side>` where `<side>` is `left` or `right`.

```json
{ "state": true }
```

`GET /api/laser/status` returns `{"left": bool, "right": bool}`.

## RGB LED

`POST /api/led/color`

```json
{ "r": 0, "g": 0, "b": 255 }
```

Each channel is an integer `0..255`.

`GET /api/led/status` returns the current `{"r", "g", "b"}` values.

## USB Camera

`GET /api/camera/usb/status`

```json
{ "success": true, "camera": "usb", "available": true }
```

`available` is `true` only if the camera device could actually be opened
(configured index or a working fallback index).

`GET /api/camera/usb/frame`

- `200` with `image/jpeg` body when a frame was captured successfully.
- `503 {"error": "Camera unavailable"}` when no USB camera device could be
  opened (configured index and all fallback indices `0,1,2,3` failed).
- `502 {"error": "Camera capture failed"}` when the device opened but a frame
  read failed.

The Pi camera exposes the equivalent `/api/camera/pi/status` and
`/api/camera/pi/frame` endpoints with the same response shape.
