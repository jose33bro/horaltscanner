# Wiring Diagram (Concept)

- **Creality V4.2.2 (STM32F103)**
  - STEP/DIR/EN vers moteurs X (translation), Y (plateau rotatif), Z (hauteur)
  - PA0: ventilateur Creality (PWM)
  - PA8: ventilateur température carte (PWM)
  - PC5: thermistance carte (EPCOS 100K B57560G104F)
  - Endstop X: point 0 translation
  - Endstop Y: point 0 après un tour complet
  - Endstop Z: point 0 alignement Lidar TF-Luna + caméra USB Logitech
- **Raspberry Pi 4**
  - USB vers carte Creality V4.2.2 (protocole custom)
  - USB vers Lidar TF-Luna
  - USB vers caméra Logitech
  - DSI vers caméra Pi V3 NoIR
  - GPIO27/22: lasers gauche/droit
  - GPIO18/13/19: LED RGB PWM
  - GPIO23: ventilateur Pi tout-ou-rien (`1` marche, `0` arrêt)

Toutes les sorties Raspberry Pi sont actives à l'état haut: `1` active la
sortie et `0` la désactive. Les charges doivent être commandées par un étage
adapté (résistance/transistor/MOSFET); elles ne doivent pas être alimentées
directement par une broche GPIO.

> GPIO18 ne doit pas être réservé par `dtoverlay=gpio-ir`, car il commande le
> canal rouge de la LED RGB.
