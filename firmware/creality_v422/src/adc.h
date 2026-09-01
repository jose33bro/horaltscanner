#ifndef ADC_H
#define ADC_H

#include <stdint.h>

/* ADC channel for NTC 100K thermistor on PA0 (ADC0). */
#define ADC_CHANNEL_THERMISTOR 0u
#define ADC_RESOLUTION         4096u   /* 12-bit ADC */

/**
 * Initialise ADC peripheral (PA0 in analog input mode, single-conversion).
 * Must be called once from firmware_init().
 */
void adc_init(void);

/**
 * Perform a blocking single conversion on the given channel.
 * Returns a raw ADC value [0..4095].
 */
uint16_t adc_read(uint8_t channel);

#endif /* ADC_H */
