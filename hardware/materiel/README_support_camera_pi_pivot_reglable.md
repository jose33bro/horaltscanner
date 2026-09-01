# Support caméra Pi v3 noir – pivot réglable (M5) + roue crantée

Ce document décrit les pièces STL, les cotes fonctionnelles, l’assemblage et les réglages d’impression (Klipper + PLA Creality Hyper Series).

## Fichiers STL

- `hardware/cad/pi_camera_tilt_mount/stl/pi_camera_tilt_base.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/ball_screw_M5x40_ball5_square_flat.stl`
- `hardware/cad/pi_camera_tilt_mount/stl/knurled_wheel_D100_T15_pitch5_flattooth.stl`

## Fonction mécanique

### 1) Base pivot caméra
- Pièce : `pi_camera_tilt_base.stl`
- Rectangle vide (slot) déplacé vers l’avant sur la plaque basse.
- Passage de réglage positionné à **27 mm du haut** de la plaque.
- Passage en **taraudage interne M5x0.8** (imprimable).

### 2) Tige filetée de réglage
- Pièce : `ball_screw_M5x40_ball5_square_flat.stl`
- Filetage externe : **M5x0.8** (hélicoïdal réel).
- Longueur filetée : **40 mm**.
- Extrémité 1 : **boule Ø5 mm max**.
- Extrémité 2 : **carré 4x4 mm**, longueur 8 mm.
- Au centre du carré : perçage **M3 (pré-taraudage 2.5 mm)**, profondeur **6 mm**.

### 3) Roue crantée
- Pièce : `knurled_wheel_D100_T15_pitch5_flattooth.stl`
- Diamètre : **100 mm**
- Épaisseur : **15 mm**
- Dents : **plates** (non pointues), écartement/pas **5 mm**
- Centre : carré **4.2 x 4.2 mm** (emboîtement sur tige 4x4)
- Passage vis : trou lisse **M3 (Ø3.2 mm)** traversant

## Assemblage

1. Visser la tige M5 dans le taraudage M5 de la base.
2. Emboîter la roue sur le carré de la tige.
3. Insérer une vis M3 dans la roue (passage lisse).
4. La vis M3 prend dans le trou M3 de la tige (profondeur 6 mm).
5. Serrer pour bloquer la roue sur la tige.

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

### Ajustement fit filetage
- Trop serré : compensation XY à **-0.06 mm**
- Trop lâche : remonter à **-0.02 mm** ou **0.00 mm**

## Orientation / supports

### `pi_camera_tilt_base.stl`
- Orientation : grand dos de la plaque contre le plateau.
- Supports : **Oui**
  - Type : Everywhere
  - Overhang : 55°
  - Densité : 12%
  - Interface : ON (2 couches)
  - Z distance : 0.22 mm

### `ball_screw_M5x40_ball5_square_flat.stl`
- Orientation : déjà à plat.
- Supports : Non (ou “touching buildplate only” si besoin).

### `knurled_wheel_D100_T15_pitch5_flattooth.stl`
- Orientation : grande face à plat.
- Supports : Non.

## Génération STL

Depuis la racine du repo :

```bash
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

## Notes
- Les filetages sont modélisés pour impression FDM.
- Pour un ajustement parfait, un passage léger au taraud M3/M5 est possible après impression.
