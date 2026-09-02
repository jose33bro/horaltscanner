# Creality 4.2.2 temperature self-check

## Connection and sensor mapping

HoralScanner uses a direct USB serial connection to the custom STM32 firmware on
the Creality 4.2.2 board. It does **not** use Klipper or the Moonraker API for
this reading. The default MCU device is `/dev/horalscanner_mcu`, at 115200 baud,
configured in `config/horalscanner_config.json`.

The read-only API is:

- `GET /api/temperature/board`
- `GET /api/temperature/creality` (alias)

The backend sends the ASCII command `TEMP_PC5_READ` over the serial link. The
firmware reads the thermistor connected to **PC5**, converts it using the EPCOS
100K B57560G104F parameters, and returns `OK TEMP_PC5 <degrees-C>`. A missing,
out-of-range, or disconnected probe returns `ERR TEMP_SENSOR` or
`ERR TEMP_RANGE`, and the API reports an unavailable sensor with HTTP 502.

The supported sensor is the **MCU/board thermistor on PC5**. Hotend and heated
bed sensors are not used: the firmware forces heater outputs off and does not
expose hotend/bed temperature channels.

## Automatic control

The PA8 fan is controlled automatically from the PC5 reading using hysteresis.
The default thresholds are 35 °C off and 39 °C on (target 37 °C); values can be
overridden in `temperature.board_fan_control`. If the probe cannot be read, the
controller fails safe by requesting PA8 at full speed and exposes the error in
the status response. There is no manual fan switch in the control-panel widget.

PA0 remains a separate Creality fan output and is not used as the temperature
probe feedback channel.
