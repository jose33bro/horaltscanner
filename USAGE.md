# HoralScanner — Usage Guide

## Web Dashboard

Once the service is running, open your browser at:

```
http://<raspberry-pi-ip>:5000
```

### Controls

| Widget | Description |
|--------|-------------|
| 🔴 **Lasers** | Toggle left/right laser on/off |
| 🟡 **LED RGB** | Drag R/G/B sliders or click colour presets |
| ⚙️ **Motors** | Set X/Y/Z displacement (mm) and click **Move**; use **Home All** to zero axes; **⏹ Stop** for emergency stop |
| 💨 **Fans** | Set Pi / Creality / Temp fan speed (%) and click **Apply Fans** |
| 🌡️ **Temperature** | Live board temperature from PC5 sensor |
| 📡 **Status** | API health and driver availability |

The dashboard auto-refreshes every **5 seconds**.

---

## API Reference

Base URL: `http://<host>:5000`

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | API health, driver availability, version |

**Response:**
```json
{
  "success": true,
  "status": {
    "api": "ok",
    "gpio_driver": true,
    "stm32_driver": true,
    "version": "1.0.0"
  }
}
```

### Lasers

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/laser/<left\|right>` | `{"state": true}` | Set laser state |
| GET | `/api/laser/status` | — | Current laser states |

### LED RGB

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/led/color` | `{"r":255,"g":0,"b":0}` | Set LED colour (0–255 each) |
| GET | `/api/led/status` | — | Current LED colour |

### Motors

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/move/<x\|y\|z>` | `{"mm": 10.0}` | Move axis by distance |
| POST | `/api/home/<x\|y\|z\|all>` | — | Home axis/all |
| POST | `/api/motor/stop` | `{"axis":"all"}` | Stop motor(s) |
| GET | `/api/motor/status` | — | Positions and movement state |

### Fans

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/fan/pi` | `{"percent":50}` | Pi GPIO23 fan speed |
| POST | `/api/fan/creality` | `{"speed":0.5}` | Creality PA0 fan speed |
| POST | `/api/fan/temperature` | `{"pwm":0.75}` | Temperature PA8 fan speed |
| GET | `/api/fan/status` | — | All fan speeds |

Speed accepts: `speed` (0–1), `pwm` (0–1), or `percent` (0–100).

### Temperature

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/temperature/board` | Board temperature from PC5 (°C) |
| GET | `/api/temperature/all` | All temperature data |

---

## cURL Examples

```bash
# Health check
curl http://localhost:5000/api/status

# Turn left laser on
curl -X POST http://localhost:5000/api/laser/left \
  -H "Content-Type: application/json" \
  -d '{"state": true}'

# Set LED to red
curl -X POST http://localhost:5000/api/led/color \
  -H "Content-Type: application/json" \
  -d '{"r": 255, "g": 0, "b": 0}'

# Move X axis 10 mm
curl -X POST http://localhost:5000/api/move/x \
  -H "Content-Type: application/json" \
  -d '{"mm": 10.0}'

# Set Pi fan to 50%
curl -X POST http://localhost:5000/api/fan/pi \
  -H "Content-Type: application/json" \
  -d '{"percent": 50}'

# Read board temperature
curl http://localhost:5000/api/temperature/board
```

---

## Hardware Quick-Start

1. Connect Raspberry Pi GPIO pins as documented in `hardware/wiring_diagram.md`.
2. Plug the Creality V4.2.2 board via USB.
3. Power on and start the service: `sudo systemctl start horalscanner`.
4. Open the dashboard in a browser.
5. Use the **Status** card to confirm GPIO and STM32 drivers are available (✅).
