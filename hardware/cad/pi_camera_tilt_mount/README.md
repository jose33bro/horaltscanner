# Support orientable pour Pi Camera V3

Ce répertoire contient la base du support orientable de Pi Camera V3 et son
test d'encombrement. La plaque verticale et la tablette inférieure forment un
support en L; les deux oreilles supérieures reçoivent l'axe M3 de la caméra.

## Fichiers générés

- `stl/pi_camera_tilt_base.stl` : base orientable définitive;
- `stl/fit_test_rear_cavity_30.45x38.2.stl` : test d'encombrement à imprimer
  avant la base.

Les autres fichiers STL éventuellement présents dans ce répertoire ne sont pas
générés par `generate.py`.

## Cotes fonctionnelles de la base

- plaque verticale : 30,45 × 38,20 × 3,20 mm;
- tablette inférieure vers l'avant : projection 24,00 mm;
- parois latérales de tablette : 3,20 mm d'épaisseur et 6,20 mm de hauteur;
- rails sous la tablette : 5,00 mm de large, 16,00 mm de long et 5,00 mm de
  descente, avec un avant-trou horizontal Ø 2,70 mm dans chaque rail;
- oreilles : projection 8,70 mm, largeur 8,50 mm, hauteur 5,99 mm et espace
  central 5,33 mm;
- trou d'axe traversant : Ø 3,40 mm;
- fenêtre CSI dans la plaque verticale : 18,00 × 9,56 mm.

## Génération

Le générateur paramétrique `generate.py` dépend des bindings OpenCascade
fournis par le paquet `cadquery-ocp`. Dans un environnement Python dédié :

```bash
python3 -m pip install cadquery-ocp
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

Exécuter la commande depuis la racine du dépôt. Elle vérifie les solides avant
l'export et remplace uniquement les deux STL listés ci-dessus.

## Impression et montage

1. Imprimer d'abord le test d'encombrement à plat et vérifier l'espace arrière.
2. Imprimer la base avec le grand dos de la plaque contre le plateau.
3. Utiliser des supports « Everywhere », angle de surplomb 55°, densité 12 %,
   interface activée (2 couches) et distance Z de 0,22 mm.
4. Installer la caméra entre les oreilles, puis une vis M3, des rondelles et
   un écrou pour régler et bloquer l'inclinaison.
5. Fixer la base par les deux rails inférieurs avec des vis M3.

Le profil d'impression détaillé est documenté dans
[`../../../materiel/README_support_camera_pi_pivot_reglable.md`](../../../materiel/README_support_camera_pi_pivot_reglable.md).
