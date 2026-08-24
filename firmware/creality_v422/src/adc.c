#include "adc.h"
#include <stdint.h>

/* -----------------------------------------------------------------------
 * Weak stubs so the translation unit compiles without a BSP.
 * On the real STM32F103 these are replaced by the HAL / LL driver.
 * ----------------------------------------------------------------------- */

__attribute__((weak)) void adc_init(void) {
    /*
     * Hardware steps (STM32F103 bare-metal):
     *   1. Enable RCC for ADC1 and GPIOA.
     *   2. Configure PA0 as analog input (CRL bits CNF=00, MODE=00).
     *   3. Power-on ADC1 (ADC_CR2_ADON), wait ≥ 1 µs.
     *   4. Run ADC calibration (ADC_CR2_CAL).
     *   5. Set sample time for CH0 to ≥ 239.5 cycles (ADC_SMPR2).
     */
}

__attribute__((weak)) uint16_t adc_read(uint8_t channel) {
    (void)channel;
    /* Default: return mid-scale so temperature reads ~25 °C in simulation. */
    return 2048u;
}
