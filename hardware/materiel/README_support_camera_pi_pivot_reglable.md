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
- `hardware/cad/pi_camera_tilt_mount/stl/camera_carrier_v3_25x24_tab4.8.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/camera_front_cover_v3_clip.stl`

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
  de long) à 16,20 mm du haut, décalé de 8,00 mm sur le côté, au dos : la
  tige d'ajustement s'y visse et sa bille appuie sur le dos de la caméra pour
  l'incliner autour de l'axe des oreilles en tournant la roue. Position basse
  (proche de la fenêtre CSI) pour un meilleur bras de levier.
- La partie tablette de 24,00 mm reçoit un passage central de 18,00 mm de
  large (même largeur que la fenêtre CSI, pour que la nappe reste libre sans
  se faire pincer) qui traverse toute l'épaisseur (3,20 mm), pour laisser
  sortir la nappe CSI par le dessous de la tablette.

### Berceau caméra
- Pièce : `camera_carrier_v3_25x24_tab4.8.stl`
- Porte la carte Pi Camera Module 3 (noir/NoIR), 25 × 24 mm, 4 trous Ø 2,50 mm
  en carré de 21,00 mm (cotes officielles Raspberry Pi).
- Tenon de charnière (4,80 mm de large) qui se clipse dans l'espace de
  5,33 mm entre les oreilles de la base, aligné sur le même axe M3 Ø 3,40 mm.
- Fossette au dos (Ø bille + 0,30 mm de jeu, 1,00 mm de profondeur) alignée
  sur le bossage de réglage de la base : la bille de la tige d'ajustement
  s'y loge pour ne pas glisser pendant le réglage.

### Cache avant (clip, sans vis)
- Pièce : `camera_front_cover_v3_clip.stl`
- Plaque 25 × 24 × 1,60 mm avec ouverture Ø 11,00 mm pour l'objectif.
- 4 pions Ø 2,30 mm (serrage léger dans les trous Ø 2,50 mm de la carte),
  pointe conique pour l'insertion, longueur de pénétration ~2,90 mm
  (traverse la carte + une grande partie du berceau par friction).
- Remplace les vis/écrous M2,5 : on clipse la carte entre le berceau et ce
  cache, sans outil.

## Assemblage

1. Imprimer d'abord `fit_test_rear_cavity_30.45x38.2.stl` et valider
   l'encombrement.
2. Poser la carte Pi Camera Module 3 contre la face avant du berceau
   (`camera_carrier_v3_25x24_tab4.8.stl`), trous alignés.
3. Clipser le cache avant (`camera_front_cover_v3_clip.stl`) par-dessus : les
   4 pions traversent les trous de la carte et se bloquent par pression dans
   les trous du berceau — pas de vis ni d'écrou nécessaires.
4. Installer le berceau (carte + cache) entre les oreilles de la base avec
   l'axe M3 traversant comme pivot, sans serrer à fond.
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

### `camera_carrier_v3_25x24_tab4.8.stl`
- Orientation : dos de la plaque (côté fossette) contre le plateau.
- Supports : généralement pas nécessaires (pièce plate, tenon fin en
  surplomb léger) — activer « Everywhere » si le tenon accroche mal.

### `camera_front_cover_v3_clip.stl`
- Orientation : face des pions contre le plateau (pions imprimés en
  surplomb léger vers le haut, cône vers le haut).
- Supports : pas nécessaires si orienté ainsi; sinon activer « Everywhere »
  pour les pions.

## Génération STL

Depuis la racine du repo :

```bash
python3 -m pip install cadquery-ocp
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

## Notes
- La commande régénère les six STL listés ci-dessus : la base, le test
  d'encombrement, la tige d'ajustement, la roue/crank, le berceau caméra et
  le cache avant à clips.
