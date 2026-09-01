# Firmware USB personnalisé (Creality V4.2.2)

Ce dossier contient une base de firmware USB custom pour STM32F103 (carte Creality V4.2.2).

## Responsabilités
- Communication USB bidirectionnelle avec le Raspberry Pi
- Commandes moteurs sur axes X/Y/Z
- Lecture endstop Y
- Point de synchronisation avec les capteurs côté Raspberry Pi

## Protocole texte minimal (USB CDC)
- `PING` → `OK PONG`
- `MOVE <AXIS> <STEPS> <SPEED>` → `OK MOVE`
- `HOME Y` → `OK HOME`
- `ENDSTOP Y` → `OK ENDSTOP <0|1>`
- `SYNC <TOKEN>` → `OK SYNC <TOKEN>`

Le code source de référence est dans `creality_v422/src/main.c`.
