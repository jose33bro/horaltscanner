# Fan Wiring Diagram – 24 V Fan via 5 V Relay (Raspberry Pi GPIO)

## Overview

The 24 V printer cooling fan is switched by a 5 V relay module.  The relay coil
is driven from a Raspberry Pi 4 GPIO pin (BCM 17 by default) through a
transistor/optocoupler on the relay board.  A flyback diode (1N4007) protects
against inductive kick.

---

## Wiring diagram

```
Raspberry Pi 4                Relay Module (5 V coil)           24 V Fan
────────────────              ───────────────────────           ────────
GPIO 17 (BCM) ──────────────► IN (signal)
3.3 V / 5 V ────────────────► VCC
GND ─────────────────────────► GND

                              NO (Normally Open) ──────────────► Fan (+)
                              COM ──────────────── 24 V PSU (+)
24 V PSU (−) ──────────────────────────────────────────────── Fan (−)

Flyback diode (1N4007):
  Anode ─── Fan (−)  /  Cathode ─── Fan (+)   [across fan terminals]
```

---

## Component list

| Component | Specification |
|-----------|---------------|
| Relay module | 5 V coil, 10 A / 250 VAC contacts |
| Fan | 24 V DC, ≤ 500 mA (12 W) |
| Flyback diode | 1N4007 (1 A, 1000 V) |
| GPIO pin | BCM 17 (configurable) |

---

## Safety notes

* Use a relay with an optocoupler to isolate Raspberry Pi logic from the 24 V
  power supply.
* The flyback diode **must** be installed across the fan terminals.
* Route 24 V wiring away from signal cables.
* Maximum relay contact current must exceed fan inrush current (typically 3×
  steady-state for DC fans).
