# Support caméra Pi v3 noir – pivot réglable

Ce document décrit l’impression et l’assemblage de la base orientable de Pi
Camera V3 (Klipper + PLA Creality Hyper Series). Les cotes et la génération du
modèle sont documentées dans
[`../cad/pi_camera_tilt_mount/README.md`](../cad/pi_camera_tilt_mount/README.md).

## Fichiers STL

- `hardware/cad/pi_camera_tilt_mount/stl/pi_camera_tilt_base.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/fit_test_rear_cavity_30.45x38.2.stl`

## Fonction mécanique

### Base pivot caméra
- Pièce : `pi_camera_tilt_base.stl`
- Fenêtre CSI : **18,00 × 9,56 mm** dans la plaque verticale.
- Deux oreilles reçoivent la caméra et son axe traversant M3.
- Les deux rails inférieurs reçoivent une vis M3 depuis chaque côté.

## Assemblage

1. Imprimer d'abord `fit_test_rear_cavity_30.45x38.2.stl` et valider
   l'encombrement.
2. Installer la caméra entre les oreilles de la base.
3. Insérer une vis M3 traversante, des rondelles et un écrou.
4. Régler l'inclinaison et serrer l'écrou.
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
- La commande régénère `pi_camera_tilt_base.stl` et le test d'encombrement;
  elle ne génère pas les autres STL de ce répertoire.
