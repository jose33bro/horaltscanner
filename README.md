# Horaltscanner

Projet de scanner 3D modulaire Raspberry Pi + Creality V4.2.2 avec firmware USB personnalisé (sans Marlin/Klipper).

## Structure actuelle

```
firmware/
├── creality_v422/
│   └── usb_firmware.c         # Firmware STM32F103 + protocole USB
├── raspberry_pi/
│   ├── usb_driver.py          # Driver protocole USB
│   ├── motor_control.py       # Orchestration axes X/Y/Z
│   ├── gpio_laser_control.py  # Contrôle des 2 lasers GPIO
│   └── scanner_app.py         # Orchestration scan + capture
hardware/
└── wiring_diagram.md
software/
└── tests/                     # Tests unitaires Python
```

## Tests

```bash
python -m unittest discover -s software/tests -p 'test_*.py'
```
