# Horaltscanner

Projet de scanner 3D modulaire pour Raspberry Pi 4 + carte mère Creality V4.2.2 avec firmware USB personnalisé (sans Marlin/Klipper).

## Objectif
- Piloter les moteurs X/Y/Z via un protocole USB binaire dédié
- Contrôler 2 lasers et l'éclairage RGB via GPIO du Raspberry Pi
- Intégrer les capteurs: lidar TF-Luna, caméra USB Logitech, caméra Pi V3 (DSI)
- Exposer une API REST et une interface web pour l'orchestration du scanner

## Structure du dépôt
- `firmware/` : firmware STM32 et pilotes Raspberry Pi bas niveau
- `software/api/` : API Flask et intégration applicative
- `software/drivers/` : couche de contrôle matériel STM32/GPIO
- `software/web/` : interface web HoralScanner PRO
- `software/tests/` : tests unitaires Python
- `hardware/` et `docs/` : documentation matérielle et technique

## Tests

```bash
python -m unittest discover -s software/tests -p 'test_*.py'
```
