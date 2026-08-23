# Matériel cible

- Raspberry Pi 4 (4Go)
- Carte mère Creality V4.2.2 (STM32F103)
- Axe X: plateau tournant
- Axe Y: translation avec endstop (point 0 lidar TF-Luna)
- Axe Z: ajustement hauteur
- Lidar TF-Luna (USB)
- Caméra USB Logitech
- Caméra Pi V3 noire (DSI)
- 2 lasers pilotés via GPIO du Raspberry Pi

La logique moteur est embarquée côté firmware STM32, la synchronisation capteurs est orchestrée côté Raspberry Pi.
