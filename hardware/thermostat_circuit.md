# Thermostat Circuit – NTC 100K on Creality V4.2.2

## Overview

A 100 kΩ NTC thermistor (B3950) mounted near the stepper drivers reads board
temperature.  The MCU converts the ADC voltage to °C using the Steinhart-Hart
(β-coefficient) formula and reports it over USB.

---

## Schematic (voltage divider)

```
+3.3 V
   |
  [4.7 kΩ pull-up resistor]
   |
   +-----> PA0 (ADC0) on STM32F103
   |
  [NTC 100 kΩ @ 25 °C  (B = 3950 K)]
   |
 GND
```

---

## Component values

| Component | Value | Note |
|-----------|-------|------|
| NTC thermistor | 100 kΩ @ 25 °C | B3950 series |
| Pull-up resistor | 4.7 kΩ | 1 % tolerance recommended |
| Reference voltage | 3.3 V | MCU VDDA |
| ADC resolution | 12 bit (4096 counts) | STM32F103 ADC1 |
| MCU pin | PA0 | ADC channel 0 |

---

## Conversion formula (β-coefficient Steinhart-Hart)

```
R_NTC = R_pullup × (ADC_MAX / ADC_raw − 1)

1/T [K] = 1/T₀ + (1/B) × ln(R_NTC / R₀)

T [°C] = T [K] − 273.15
```

Where `T₀ = 298.15 K (25 °C)`, `B = 3950 K`, `R₀ = 100 000 Ω`.

---

## Wiring notes

* Keep traces short between NTC and PA0 to reduce noise.
* A 100 nF ceramic capacitor from PA0 to GND filters ADC noise.
* The NTC can be epoxied to a heatsink tab or placed near the TMC drivers.
