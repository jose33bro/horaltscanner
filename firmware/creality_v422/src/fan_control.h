#ifndef FAN_CONTROL_H
#define FAN_CONTROL_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Fan relay control.
 *
 * The 24 V fan is driven by a 5 V relay coil connected to a GPIO output pin.
 * The relay coil GPIO defaults to PB0 (configurable at init time).
 *
 * Hysteresis thresholds (configurable via USB command SET_FAN_THRESHOLD):
 *   FAN_ON  : temperature > fan_threshold_on   (default 50 °C)
 *   FAN_OFF : temperature < fan_threshold_off  (default 45 °C)
 */

/**
 * Initialise the fan relay GPIO pin (set as output, relay open = fan off).
 * @param relay_gpio_pin  GPIO pin number for the relay coil signal.
 */
void fan_control_init(uint8_t relay_gpio_pin);

/** Turn the fan relay ON (fan running). */
void fan_on(void);

/** Turn the fan relay OFF (fan stopped). */
void fan_off(void);

/** Return true if the fan relay is currently ON. */
bool fan_is_on(void);

/**
 * Set temperature thresholds for automatic fan control.
 * @param on_celsius   Turn fan on when temperature exceeds this value.
 * @param off_celsius  Turn fan off when temperature drops below this value.
 */
void fan_set_threshold(float on_celsius, float off_celsius);

/**
 * Evaluate the current temperature and switch the fan relay accordingly.
 * Must be called periodically (e.g. every 1 s from the main loop).
 * @param current_temp_celsius  Current board temperature.
 */
void fan_control_update(float current_temp_celsius);

#endif /* FAN_CONTROL_H */
