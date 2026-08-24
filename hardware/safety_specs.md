# Safety Specifications – Thermal Management

## Temperature thresholds

| Event | Threshold | Action |
|-------|-----------|--------|
| Fan ON | > 50 °C | Relay closes, fan starts |
| Fan OFF | < 45 °C | Relay opens, fan stops (5 °C hysteresis) |
| Warning alert | > 55 °C | Logged / reported over USB |
| Emergency stop | ≥ 60 °C | All stepper motors halted immediately; scan aborted |

Thresholds can be reconfigured at runtime via `SET_FAN_THRESHOLD` (USB) or
`set_fan_threshold()` (Python driver / GPIO controller).

---

## Firmware safety (STM32F103)

* `firmware_handle_packet()` reads temperature **before** executing any motor
  command.
* If temperature ≥ `TEMP_EMERGENCY_STOP` (60 °C):
  * `motor_stepper_stop_all()` is called.
  * Response returns `STATUS_ERROR` with error code `ERR_THERMAL_SHUTDOWN`
    (`0x20`).
  * No motor movement command is executed.
* Fan is updated automatically on every command via `fan_control_update()`.

---

## Raspberry Pi safety (Python)

* `FanGPIOController.update()` raises `OverheatError` if temperature ≥ 60 °C.
* `ScannerApp.run_scan()` raises `ScanAbortedError`:
  * Before scan: if temperature ≥ 55 °C (pre-scan limit).
  * During scan: if `FanGPIOController` detects emergency.
* The fan monitoring thread (`start_monitoring()`) runs as a daemon and
  continuously updates the relay based on MCU temperature readings.

---

## NTC sensor range

| Parameter | Value |
|-----------|-------|
| Sensor type | NTC 100 kΩ, B3950 |
| Measurement range | −40 °C to +125 °C |
| ADC resolution | 12 bit |
| Typical accuracy | ±1 °C (25–85 °C range) |
