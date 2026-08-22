# Horaltscanner

Projet de scanner 3D modulaire pour Raspberry Pi 4 + carte mère Creality V4.2.2 avec firmware USB personnalisé (sans Marlin/Klipper).

## Objectif
- Piloter les moteurs X/Y/Z via USB
- Gérer l'endstop Y (point 0 côté lidar)
- Contrôler 2 lasers via GPIO du Raspberry Pi
- Intégrer les capteurs: lidar TF-Luna, caméra USB Logitech, caméra Pi V3 (DSI)
- Orchestrer l'acquisition et préparer la reconstruction de nuage de points

## Structure du dépôt
- `firmware/` : firmware USB custom STM32F103 (Creality V4.2.2)
- `software/` : application Python côté Raspberry Pi (drivers + orchestration)
- `hardware/` : documentation matérielle / câblage
- `docs/` : documentation technique et protocole
