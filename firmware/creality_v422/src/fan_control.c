#include "fan_control.h"
#include "temperature.h"
#include <stdint.h>

static bool    g_fan_on          = false;
static float   g_threshold_on    = TEMP_FAN_ON_DEFAULT;
static float   g_threshold_off   = TEMP_FAN_OFF_DEFAULT;
static uint8_t g_relay_gpio_pin  = 0;

/* -----------------------------------------------------------------------
 * Weak HAL stubs – replaced by the real GPIO driver on the target board.
 * ----------------------------------------------------------------------- */

__attribute__((weak)) void _fan_gpio_init(uint8_t pin)   { (void)pin; }
__attribute__((weak)) void _fan_gpio_write(uint8_t pin, bool value) { (void)pin; (void)value; }

/* ----------------------------------------------------------------------- */

void fan_control_init(uint8_t relay_gpio_pin) {
    g_relay_gpio_pin = relay_gpio_pin;
    _fan_gpio_init(relay_gpio_pin);
    fan_off();
}

void fan_on(void) {
    g_fan_on = true;
    _fan_gpio_write(g_relay_gpio_pin, true);
}

void fan_off(void) {
    g_fan_on = false;
    _fan_gpio_write(g_relay_gpio_pin, false);
}

bool fan_is_on(void) {
    return g_fan_on;
}

void fan_set_threshold(float on_celsius, float off_celsius) {
    g_threshold_on  = on_celsius;
    g_threshold_off = off_celsius;
}

void fan_control_update(float current_temp_celsius) {
    if (!g_fan_on && current_temp_celsius > g_threshold_on) {
        fan_on();
    } else if (g_fan_on && current_temp_celsius < g_threshold_off) {
        fan_off();
    }
}
