# Support caméra Pi v3 noir – pivot réglable

Ce document décrit l’impression et l’assemblage de la base orientable de Pi
Camera V3 (Klipper + PLA Creality Hyper Series). Les cotes et la génération du
modèle sont documentées dans
[`../cad/pi_camera_tilt_mount/README.md`](../cad/pi_camera_tilt_mount/README.md).

## Fichiers STL

- `hardware/cad/pi_camera_tilt_mount/stl/pi_camera_tilt_base.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/fit_test_rear_cavity_30.45x38.2.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/adjustment_rod_M5x50_ball6.5_square_m3.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/wheel_crank_50mm_square_m3.stl`

## Fonction mécanique

### Base pivot caméra
- Pièce : `pi_camera_tilt_base.stl`
- Fenêtre CSI : **18,00 × 9,56 mm** dans la plaque verticale, centrée bas et décalée vers l'avant.
- Deux oreilles reçoivent la caméra et son axe traversant M3.
- Les deux rails inférieurs reçoivent une vis M3 depuis chaque côté, avec un
  dépouille de 3,00 mm depuis l'avant pour dégager le passage M3.
- La plaque verticale porte un trou M5 centré entre les oreilles, à 22,00 mm du
  haut pour la fixation mécanique.
- La plaque verticale porte aussi un bossage taraudé M5 (Ø 10,00 mm, 6,00 mm
  de long) à 12,00 mm du haut, au dos : la tige d'ajustement s'y visse et sa
  bille appuie sur le dos de la caméra pour l'incliner autour de l'axe des
  oreilles en tournant la roue.
- La partie tablette de 24,00 mm reçoit un passage central de 12,00 mm de
  large qui traverse toute l'épaisseur (3,20 mm), pour laisser sortir la
  nappe CSI par le dessous de la tablette.

## Assemblage

1. Imprimer d'abord `fit_test_rear_cavity_30.45x38.2.stl` et valider
   l'encombrement.
2. Installer la caméra entre les oreilles de la base avec l'axe M3 traversant
   comme pivot, sans serrer à fond.
3. Visser la tige d'ajustement dans le bossage M5 au dos de la plaque jusqu'à
   toucher le dos de la caméra, puis clipser la roue sur le carré avec une vis
   M3.
4. Tourner la roue pour régler finement l'inclinaison.
5. Fixer la base horizontalement au support par les deux rails inférieurs avec
   une vis M3 de chaque côté.

## Réglages impression recommandés (Klipper + Creality Hyper PLA, buse 0.4)

- Temp buse : **215°C**
- Temp bed : **60°C**
- Hauteur couche : **0.16 mm**
- 1ère couche : **0.20 mm**
- Largeur ligne : **0.42 mm**
- Parois : **6**
- Top/Bottom : **7 / 7**
- Infill : **35%** (Gyroid/Cubic)
- Ventilation : **100% dès couche 3**
- Vitesse paroi externe : **22 mm/s**
- Vitesse paroi interne : **35 mm/s**
- Vitesse infill : **50 mm/s**
- Vitesse travel : **160 mm/s**
- Brim : **6 mm base**, **8 mm tige**, **3–5 mm roue**
- Compensation XY : **-0.04 mm** (point de départ)

Profil complet (start/end G-code Klipper, réglages support détaillés) :
[`PRINT_PROFILE_klipper_creality_hyper_pla.txt`](./PRINT_PROFILE_klipper_creality_hyper_pla.txt).

## Orientation / supports

### `pi_camera_tilt_base.stl`
- Orientation : grand dos de la plaque contre le plateau.
- Supports : **Oui**
  - Type : Everywhere
  - Overhang : 55°
  - Densité : 12%
  - Interface : ON (2 couches)
  - Z distance : 0.22 mm

## Génération STL

Depuis la racine du repo :

```bash
python3 -m pip install cadquery-ocp
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

## Notes
- La commande régénère les quatre STL listés ci-dessus : la base, le test
  d'encombrement, la tige d'ajustement et la roue/crank.
