# Temperature Management Guide

## Overview

The Horaltscanner thermal management system monitors the Creality V4.2.2 board
temperature via a NTC 100 kΩ thermistor wired to ADC pin PA0 on the STM32F103
MCU.  Temperature data is reported over USB and used to drive a 24 V cooling fan
connected to the Raspberry Pi via a relay.

---

## Hardware setup

### 1 – Thermistor wiring

See [`hardware/thermostat_circuit.md`](../hardware/thermostat_circuit.md).

1. Connect one leg of the NTC thermistor to PA0 on the Creality V4.2.2 board.
2. Connect the other leg to GND.
3. Add a 4.7 kΩ pull-up resistor between PA0 and the 3.3 V rail.
4. Optionally add a 100 nF bypass capacitor from PA0 to GND.

### 2 – Fan wiring

See [`hardware/fan_wiring_diagram.md`](../hardware/fan_wiring_diagram.md).

1. Connect the relay module VCC/GND to the Raspberry Pi 5 V / GND pins.
2. Connect the relay IN signal to GPIO 17 (BCM, configurable).
3. Connect the relay NO/COM contacts in series with the 24 V fan supply.
4. Install a 1N4007 flyback diode across the fan terminals.

---

## Firmware (STM32F103)

The custom firmware exposes four thermal USB commands:

| Command | Packet `command` byte | Description |
|---------|----------------------|-------------|
| `GET_TEMP` | `0x50` | Returns current temperature in the response |
| `FAN_ON` | `0x51` | Forces the fan relay ON |
| `FAN_OFF` | `0x52` | Forces the fan relay OFF |
| `SET_FAN_THRESHOLD <on> <off>` | `0x53` | Sets hysteresis thresholds (centi-°C in value/speed fields) |

Every USB response now includes a `temperature_cdeg` field (int16, signed).
Divide by 100 to obtain °C.

Safety: if temperature ≥ 60 °C, the firmware halts all motors and returns
`ERR_THERMAL_SHUTDOWN (0x20)`.

---

## Python driver (Raspberry Pi)

```python
from firmware.raspberry_pi.usb_driver import USBScannerDriver, PyUSBTransport

transport = PyUSBTransport(vendor_id=0x1234, product_id=0x5678)
driver = USBScannerDriver(transport)

# Read current board temperature
temp = driver.get_temperature()   # float, °C
print(f"Board temperature: {temp:.1f} °C")

# Control fan directly
driver.fan_on()
driver.fan_off()

# Configure automatic thresholds (on=50 °C, off=45 °C)
driver.set_fan_threshold(50.0, 45.0)
```

---

## GPIO fan controller (Raspberry Pi)

```python
from firmware.raspberry_pi.fan_gpio_control import FanGPIOController
from firmware.raspberry_pi.gpio_laser_control import RpiGPIOBackend

backend = RpiGPIOBackend()
fan = FanGPIOController(backend, pin=17, fan_on_celsius=50.0, fan_off_celsius=45.0)

# Manual control
fan.fan_on()
fan.fan_off()

# Automatic monitoring thread
fan.start_monitoring(get_temperature=driver.get_temperature, interval_s=1.0)
```

---

## ScannerApp temperature integration

```python
from firmware.raspberry_pi.scanner_app import ScannerApp, ScanAbortedError

app = ScannerApp(
    controller=controller,
    lasers=lasers,
    sensors=sensors,
    temp_source=driver,       # any object with get_temperature() -> float
    fan_controller=fan,
)

try:
    frames = app.run_scan(x_offsets=[0, 100], z_offsets=[0, 50],
                          rotation_steps=36, step_per_rotation=100)
except ScanAbortedError as e:
    print(f"Scan aborted: {e}")
```

The app will refuse to start if temperature ≥ 55 °C and will abort mid-scan if
the emergency threshold (60 °C) is reached.

---

## Safety thresholds reference

See [`hardware/safety_specs.md`](../hardware/safety_specs.md).

| Event | Threshold | Action |
|-------|-----------|--------|
| Fan ON | > 50 °C | Fan starts |
| Fan OFF | < 45 °C | Fan stops (hysteresis) |
| Pre-scan warning | ≥ 55 °C | Scan refused |
| Emergency stop | ≥ 60 °C | Motors halted, scan aborted |

---

## Calibration

The NTC calibration uses the β-coefficient formula with:
- `B = 3950 K`
- `R₀ = 100 kΩ @ 25 °C`
- `R_pullup = 4.7 kΩ`

To recalibrate, measure actual resistance at a known temperature and adjust
`TEMP_B_COEFFICIENT` in `firmware/creality_v422/src/temperature.h`.
