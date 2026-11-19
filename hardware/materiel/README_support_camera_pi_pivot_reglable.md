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
- `hardware/cad/pi_camera_tilt_mount/stl/camera_carrier_cover_v4_onepiece.stl`
  (pièce 3 = ancien berceau + ancien cache 4, une seule pièce)

## Fonction mécanique

### Base pivot caméra
- Pièce : `pi_camera_tilt_base.stl`
- Fenêtre CSI : **18,00 × 9,56 mm** dans la plaque verticale, centrée bas et décalée vers l'avant.
- Deux oreilles reçoivent la caméra et son axe traversant M3.
- Les deux rails inférieurs reçoivent une vis M3 depuis chaque côté, avec un
  dépouille de 3,00 mm depuis l'avant pour dégager le passage M3.
- La plaque verticale porte un trou M5 centré entre les oreilles, à 22,00 mm du
  haut pour la fixation mécanique.
- La partie tablette de 24,00 mm reçoit un passage central pour la nappe
  CSI, orienté vers l'avant depuis le centre.

### Berceau + capot avant (pièce 3, une seule pièce)
- Pièce : `camera_carrier_cover_v4_onepiece.stl`
- La carte Pi Camera Module 3 (noir/NoIR), 25 × 24 mm, 4 trous Ø 2,50 mm
  en carré de 21,00 mm, coulisse par le bas dans une fente de 1,30 mm entre le
  berceau (2 mm) et le capot (1,6 mm, ouverture objectif Ø 11,00 mm), jonction
  par un pont rigide en haut; 2 nervures de serrage 0,15 mm. Plus de pions.
- Tenon de charnière (4,80 mm de large) qui se clipse dans l'espace de
  5,33 mm entre les oreilles de la base, aligné sur le même axe M3 Ø 3,40 mm.
- Patin plat au dos (Ø 12 mm, 0,6 mm) pour la bille de la tige d'ajustement.

## Assemblage

1. Imprimer d'abord `fit_test_rear_cavity_30.45x38.2.stl` et valider
   l'encombrement.
2. Glisser la carte Pi Camera Module 3 par le bas dans la fente de la pièce 3
   (`camera_carrier_cover_v4_onepiece.stl`) jusqu'au pont, puis brancher la
   nappe CSI par la fente du berceau.
3. Installer la pièce 3 (carte incluse) entre les oreilles de la base avec
   l'axe M3 traversant comme pivot, sans serrer à fond.
4. (supprimé : le cache avant est fusionné dans la pièce 3.)
5. Visser la tige d'ajustement dans le bossage M5 au dos de la plaque jusqu'à
   ce qu'elle se loge dans la fossette au dos du berceau, puis clipser la roue
   sur le carré avec une vis M3.
6. Tourner la roue pour régler finement l'inclinaison.
7. Fixer la base horizontalement au support par les deux rails inférieurs avec
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

### `camera_carrier_cover_v4_onepiece.stl`
- Orientation : debout sur le bord bas (fente carte verticale), brim 3 mm.
- Supports : **arborescents légers** sous le tenon (et sous le toit de
  l'ouverture Ø 11 mm si besoin), jamais dans la fente carte. Voir
  `print_settings.json` (couche 0,12 mm, 30 %, 4 parois, 40 mm/s).

## Génération STL

Depuis la racine du repo :

```bash
python3 -m pip install cadquery-ocp
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

## Notes
- La commande régénère les STL listés ci-dessus : la base, le test
  d'encombrement, la tige d'ajustement, la roue/crank et la pièce 3 unique
  (berceau + capot avant).
