# Wiring Diagram (Concept)

- **Creality V4.2.2 (STM32F103)**
  - STEP/DIR/EN vers moteurs X (translation), Y (plateau rotatif), Z (hauteur)
  - Endstop X: point 0 translation
  - Endstop Y: point 0 après un tour complet
  - Endstop Z: point 0 alignement Lidar TF-Luna + caméra USB Logitech
- **Raspberry Pi 4**
  - USB vers carte Creality V4.2.2 (protocole custom)
  - USB vers Lidar TF-Luna
  - USB vers caméra Logitech
  - DSI vers caméra Pi V3 NoIR
  - GPIO BCM17/BCM27 vers 2 lasers structurés
