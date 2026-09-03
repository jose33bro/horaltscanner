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
  - CSI vers caméra Pi V3 NoIR
  - GPIO27/22: lasers gauche/droit, PWM 1 kHz via MOSFET
  - GPIO18/13/19: LED RGB PWM
  - GPIO23: ventilateur Pi tout-ou-rien (`1` marche, `0` arrêt)

La configuration de production utilise des sorties actives à l'état haut; le
pilote conserve aussi le comportement actif à l'état bas lorsqu'il est
configuré. Les lasers 5 V doivent être commandés par des MOSFET compatibles PWM
et démarrent à 20 % de rapport cyclique. Les autres charges doivent aussi
utiliser un étage adapté (résistance/transistor/MOSFET); aucune charge ne doit
être alimentée directement par une broche GPIO.

> GPIO18 ne doit pas être réservé par `dtoverlay=gpio-ir`, car il commande le
> canal rouge de la LED RGB.
