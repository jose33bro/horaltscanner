# Horaltscanner

Projet de scanner 3D modulaire Raspberry Pi + Creality V4.2.2 avec firmware USB personnalisé (sans Marlin/Klipper).

## API Flask (sans Klipper)

L'API principale est `software/api/horalscanner_api.py`.

### Endpoints disponibles

- `POST /api/laser/<left|right>`: active/désactive les lasers (`{"state": true|false}`)
- `POST /api/led/color`: couleur RGB (`{"r":0-255,"g":0-255,"b":0-255}`)
- `POST /api/move/<x|y|z>`: déplacement axe en mm (`{"mm": float}`)
- `POST /api/home/<x|y|z|all>`: homing d'axe(s)
- `GET|POST /api/motor/status`: état moteurs (position, mouvement, température MCU)
- `POST /api/motor/stop`: arrêt moteur (`{"axis":"x|y|z|all"}`)
- `POST /api/fan/pi`: vitesse ventilateur Pi (PWM `0-1` ou `% 0-100`)
- `POST /api/fan/creality`: vitesse ventilateur Creality PA0 (PWM `0-1` ou `% 0-100`)
- `POST /api/fan/temperature`: vitesse ventilateur thermique PA8 (PWM `0-1` ou `% 0-100`)
- `GET /api/fan/status`: vitesse de tous les ventilateurs
- `GET /api/temperature/board`: température carte Creality (PC5)
- `GET /api/temperature/all`: toutes les températures exposées par l'API

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

## Mapping matériel (printer.cfg)

### Raspberry Pi GPIO

- GPIO27: `laser_left` (digital)
- GPIO22: `laser_right` (digital)
- GPIO18: `led_red` (PWM)
- GPIO13: `led_green` (PWM)
- GPIO19: `led_blue` (PWM)
- GPIO23: `pi_fan` (PWM)

### Creality 4.2.2 (STM32F103RET6)

- PC2 / PB9 / PC3: stepper X (step/dir/enable)
- PB8 / PB7 / PC3: stepper Y (step/dir/enable)
- PB6 / PB5 / PC3: stepper Z (step/dir/enable)
- `PC3` est un enable partagé pour X/Y/Z.
- PA0: ventilateur Creality (PWM)
- PA8: ventilateur température (PWM)
- PC5: sonde température carte (`EPCOS 100K B57560G104F`)

Référence câblage: `/home/runner/work/horaltscanner/horaltscanner/hardware/wiring_diagram.md`

## Tests

```bash
python -m unittest discover -s software/tests -p 'test_*.py'
```
