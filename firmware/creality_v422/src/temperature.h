#ifndef TEMPERATURE_H
#define TEMPERATURE_H

#include <stdint.h>

/*
 * NTC 100K thermistor parameters.
 *   Pull-up resistor: 4.7 kΩ
 *   Reference voltage: 3.3 V  (ADC_RESOLUTION = 4096 counts)
 *   B-coefficient (Steinhart-Hart simplified): 3950 K (typical for NTC 100K B3950)
 *   Nominal resistance at 25 °C: 100 000 Ω
 */
#define TEMP_NTC_NOMINAL_R    100000.0f  /* NTC resistance at 25 °C, Ω */
#define TEMP_PULLUP_R          4700.0f   /* Pull-up resistor, Ω */
#define TEMP_NOMINAL_CELSIUS     25.0f   /* Reference temperature, °C */
#define TEMP_B_COEFFICIENT     3950.0f   /* Beta coefficient, K */

/* Safety thresholds (°C) */
#define TEMP_FAN_ON_DEFAULT      50.0f
#define TEMP_FAN_OFF_DEFAULT     45.0f
#define TEMP_WARN_THRESHOLD      55.0f
#define TEMP_EMERGENCY_STOP      60.0f

/**
 * Convert a raw 12-bit ADC reading to temperature in degrees Celsius.
 * Uses the simplified Steinhart-Hart (beta) formula.
 * Returns temperature in °C. Returns NaN on invalid input.
 */
float temperature_from_adc(uint16_t adc_raw);

/**
 * Read the current board temperature by sampling the NTC on ADC_CHANNEL_THERMISTOR.
 * Returns temperature in °C.
 */
float temperature_read_celsius(void);

#endif /* TEMPERATURE_H */
