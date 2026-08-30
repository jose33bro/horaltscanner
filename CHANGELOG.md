# Changelog

All notable changes to HoralScanner are documented in this file.

## [1.0.0] - 2026-08-23

### Added

**Web Dashboard UI**
- Single-page application served at `GET /` from `software/web/index.html`
- Real-time controls: laser toggles, LED RGB color picker, motor sliders, fan speed sliders
- Live temperature display and motor position readout
- Polling-based live updates (5-second interval)
- Responsive, mobile-friendly layout

**API Enhancements**
- `GET /` → serves `software/web/index.html`
- `GET /api/status` → health check (API, GPIO driver, STM32 driver availability)
- `GET /api/laser/status` → current laser states
- `GET /api/led/status` → current LED color
- CORS headers on all responses (`Access-Control-Allow-Origin: *`)
- Static file serving from `software/web/`

**Fan Control**
- `POST /api/fan/pi` — Pi GPIO23 fan output (0 = off, any positive value = on)
- `POST /api/fan/creality` — Creality PA0 fan PWM
- `POST /api/fan/temperature` — Temperature PA8 fan PWM
- `GET /api/fan/status` — aggregated fan status
- Accepts `speed` (0–1), `pwm` (0–1), or `percent` (0–100)

**Temperature Monitoring**
- `GET /api/temperature/board` — STM32 board temperature (PC5)
- `GET /api/temperature/all` — all temperature data

**Drivers**
- `STM32Driver`: fan state tracking (PA0, PA8), `get_fan_status()`, `read_board_temperature()`
- `GPIODriver`: Pi fan digital output on GPIO23

**Documentation**
- `DEPLOYMENT.md` — installation and systemd service instructions
- `USAGE.md` — web UI guide and full API reference
- `hardware/wiring_diagram.md` — updated with PA0, PA8, PC5 pin mapping

### Known Issues

- `GET /api/temperature/board` returns an error when the STM32 is not physically connected
  (PC5 ADC read over USB requires live hardware).
- The development server (`flask run`) is not recommended for production; use a WSGI server.

[1.0.0]: https://github.com/jose33bro/horaltscanner/releases/tag/v1.0.0
