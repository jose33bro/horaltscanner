#include "temperature.h"
#include "adc.h"
#include <math.h>
#include <stdint.h>

/*
 * Steinhart-Hart simplified (beta) formula:
 *
 *   1/T = 1/T0 + (1/B) * ln(R / R0)
 *
 * where:
 *   T0 = 298.15 K  (25 °C)
 *   B  = beta coefficient
 *   R0 = nominal NTC resistance at T0
 *   R  = measured NTC resistance derived from the voltage divider:
 *          R = PULLUP * (ADC_RESOLUTION / adc_raw - 1)
 */

float temperature_from_adc(uint16_t adc_raw) {
    if (adc_raw == 0u) {
        return NAN;
    }

    float r_ntc = TEMP_PULLUP_R * ((float)ADC_RESOLUTION / (float)adc_raw - 1.0f);

    float t_kelvin_inv = 1.0f / (TEMP_NOMINAL_CELSIUS + 273.15f)
                       + (1.0f / TEMP_B_COEFFICIENT) * logf(r_ntc / TEMP_NTC_NOMINAL_R);

    return (1.0f / t_kelvin_inv) - 273.15f;
}

float temperature_read_celsius(void) {
    uint16_t raw = adc_read(ADC_CHANNEL_THERMISTOR);
    return temperature_from_adc(raw);
}
