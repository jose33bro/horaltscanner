# HoralScanner — Bill of Materials (BOM)

## Overview
Complete parts list for building HoralScanner with Raspberry Pi 4 and Creality V4.2.2 controller.

---

## Computing & Control

| Part | Specification | Qty | Purpose |
|------|---|---|---|
| Raspberry Pi 4 | 4GB RAM minimum (8GB recommended) | 1 | Main controller |
| Creality V4.2.2 | STM32F103RET6 | 1 | Motor/fan/temperature control |
| Power Supply | 24V 10A USB-C or barrel jack | 1 | Pi + Creality board |
| Micro-USB Cable | Data-capable (power + signal) | 1 | Pi ↔ Creality communication |
| SD Card | 64GB A1/A2, UHS-I minimum | 1 | Raspberry Pi OS (Bookworm) |

---

## Mechanical — Motion System (Creality Hyper Series)

| Part | Specification | Qty | Notes |
|------|---|---|---|
| **Ball Screw Assembly** | M5 × 40 mm, ball Ø6.5 mm | 3 | X, Y, Z axes (NEMA 17 stepper compatible) |
| **Stepper Motors** | NEMA 17, 1.68A, 42N·cm | 3 | X, Y, Z axes (standard Creality) |
| **Motion Platform Base** | Aluminum or steel frame | 1 | Foundation for all three axes |

---

## 3D Printed Parts (PLA - Creality Hyper Series)

### Camera Support Plate
| Component | Dimension | Qty | Material | Notes |
|---|---|---|---|---|
| **Camera Support Plate** | 28.05 × 7 × 1 mm | 1 | PLA | USB camera mounting bracket |
| **Socket Diameter** | Ø6.9 mm, centered | 1 | — | Camera lens/connector alignment |
| **Petal Retainers** | 4 mm depth | 4 | PLA | Camera retention mechanism |
| **M3 Mounting Holes** | Ø3.2 mm (clearance) | 2 | — | Frame attachment points |

### Base Piece
| Component | Specification | Qty | Notes |
|---|---|---|---|---|
| **Base Plate** | — | 1 | PLA | Foundation for vertical assembly |
| **M5 Hole** | Tapped or clearance M5 | 1 | Vertical mounting point | Ball screw integration |
| **Orientation** | Rear → Front | 1 | — | Z-axis (height) motion direction |
| **Vertical Offset** | +5 mm from origin | 1 | — | Calibration reference height |

---

## Sensing & Vision

| Part | Specification | Qty | Purpose |
|------|---|---|---|
| **TF-Luna LiDAR** | USB interface, 8m range | 1 | Distance measurement for Y-axis sync |
| **Logitech USB Camera** | USB 2.0, 1080p @ 30fps (typical) | 1 | Point cloud RGB texture |
| **Raspberry Pi Camera V3** | DSI ribbon, 12MP, noir | 1 | Alternative/backup RGB capture |

---

## GPIO-Controlled Devices (Raspberry Pi)

| Component | Specification | GPIO Pin | Qty | Purpose |
|---|---|---|---|---|
| **Laser (Left)** | 650nm class-3B or lower | GPIO 27 | 1 | Structured light projection |
| **Laser (Right)** | 650nm class-3B or lower | GPIO 22 | 1 | Dual-laser triangulation |
| **LED Red** | 3mm or 5mm, common cathode | GPIO 18 (PWM) | 1 | Illumination |
| **LED Green** | 3mm or 5mm, common cathode | GPIO 13 (PWM) | 1 | Illumination |
| **LED Blue** | 3mm or 5mm, common cathode | GPIO 19 (PWM) | 1 | Illumination |
| **Fan (Pi Cooling)** | 5V 0.2A radial or axial | GPIO 23 | 1 | Thermostat: ON @ 55°C, OFF @ 45°C |

---

## Stepper Motor Drivers (STM32 Side - Creality V4.2.2)

| Axis | Step Pin | Dir Pin | Enable Pin | Microstepping | Steps/mm |
|---|---|---|---|---|---|
| **X** | PC2 | PB9 | PC3 | 16× | (configured) |
| **Y** | PB8 | PB7 | PC3 | 16× | (configured) |
| **Z** | PB6 | PB5 | PC3 | 16× | (configured) |

---

## PWM-Controlled Fans (Creality Board)

| Fan | Pin | PWM Range | Purpose |
|---|---|---|---|
| **Creality Fan** | PA0 | 0–255 | Board active cooling |
| **Temperature Fan** | PA8 | 0–255 | Auxiliary thermal regulation |

---

## Analog Sensors (Creality Board)

| Sensor | Pin | Input | Purpose |
|---|---|---|---|
| **Board Thermistor** | PC5 (ADC) | EPCOS 100K B57560G104F | Temperature monitoring |
| **Endstop (Y-axis)** | (TBD) | Digital (normally open) | Homing reference for Y |

---

## Cabling & Connectors

| Description | Type | Length | Qty |
|---|---|---|---|
| USB-A to USB-Micro | 2.0 High-Speed | 2m | 1 | Pi ↔ Creality |
| USB-A to USB-Micro | 2.0 High-Speed | 1.5m | 1 | Pi ↔ TF-Luna |
| USB-A to USB-Micro | 2.0 High-Speed | 1m | 1 | Pi ↔ Logitech Camera |
| DSI Ribbon Cable | 22-pin | stock | 1 | Pi ↔ Pi Camera V3 |
| Dupont Jumper Wires | F-F 2.54mm | 200mm | 20 | GPIO connections |
| Stepper Motor Cable | 4-wire 28AWG | 500mm | 3 | NEMA 17 → Creality |
| Power Cable | 24V barrel jack | 2m | 1 | PSU → Pi + Creality |

---

## Optional/Future Components

| Part | Specification | Purpose |
|---|---|---|
| Enclosure | 3D-printed or aluminum | Dust protection, thermal regulation |
| Calibration Cube | PLA 20×20×20 mm | Accuracy verification |
| Replacement Ball Screws | M5 × 40 (spare) | Wear replacement |
| Extra Stepper Motors | NEMA 17 (spare) | Maintenance stock |

---

## Assembly Notes

- **PLA Parts Printing:** Creality Hyper Series settings recommended (210°C, 80 mm/s, 15% infill for support brackets)
- **Ball Screw Integration:** M5 hole on base must be **tapped** (M5×0.8 pitch) or use threaded insert
- **Camera Plate Alignment:** Socket (Ø6.9) centers lens; petals (4 mm) retain without glue
- **Vertical Offset Calibration:** +5 mm from origin ensures proper TF-Luna Y-axis sync
- **GPIO Wiring:** Use 330Ω resistors for LEDs; optocouplers recommended for laser safety

---

## Version History

| Date | Version | Changes |
|---|---|---|
| 2026-08-29 | 1.0.0 | Initial BOM with Creality Hyper Series specs, PLA parts, GPIO mapping |

