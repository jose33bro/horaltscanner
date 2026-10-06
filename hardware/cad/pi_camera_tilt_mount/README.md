# Support orientable pour Pi Camera V3

Ce répertoire contient la base du support orientable de Pi Camera V3 et son
test d'encombrement. La plaque verticale et la tablette inférieure forment un
support en L; les deux oreilles supérieures reçoivent l'axe M3 de la caméra.

## Fichiers générés

- `stl/pi_camera_tilt_base.stl` : base orientable définitive;
- `stl/fit_test_rear_cavity_30.45x38.2.stl` : test d'encombrement à imprimer
  avant la base;
- `stl/adjustment_rod_M5x50_ball6.5_square_m3.stl` : tige d'ajustement M5
  sur 50 mm, bille Ø 6,5 mm côté caméra et carré côté roue/plateau, avec trou
  M3 central dans le carré;
- `stl/wheel_crank_50mm_square_m3.stl` : roue/crank de 50 mm de diamètre avec
  carré de montage et trou M3 central pour serrage sur plaque de 3 mm.

Les STL de l'ancienne conception « vis à bille + socle à pétales »
(`ball_screw_M5x40_ball6.5.stl`, `camera_support_plate_28.05x7x1.stl`) ainsi
que l'ancien test d'encombrement racine (`fit_test_27.6x7.3.stl`) ont été
retirés : ils correspondaient à une itération antérieure, incompatible avec
la base actuelle (fixation par tige d'ajustement + roue/crank). Les quatre
STL ci-dessus sont les seuls à utiliser.

## Cotes fonctionnelles de la base

- plaque verticale : 30,45 × 38,20 × 3,20 mm;
- tablette inférieure vers l'avant : projection 24,00 mm;
- parois latérales de tablette : 3,20 mm d'épaisseur et 6,20 mm de hauteur;
- rails sous la tablette : 5,00 mm de large, 16,00 mm de long et 5,00 mm de
  descente, avec un avant-trou horizontal Ø 2,70 mm dans chaque rail et une
  découpe de 3,00 mm depuis l'avant pour dégager le passage M3;
- passage de nappe du câble CSI dans la partie tablette : ouverture centrale
  de 18,00 mm de large (même largeur que la fenêtre CSI de la plaque, pour
  que la nappe garde un passage libre et constant, sans se faire pincer),
  débouchant de part en part (dessus/dessous) de la tablette de 3,20 mm
  d'épaisseur, pour laisser sortir la nappe par le dessous;
- oreilles : projection 8,70 mm, largeur 8,50 mm, hauteur 5,99 mm et espace
  central 5,33 mm;
- trou d'axe traversant : Ø 3,40 mm (pivot de la caméra);
- trou de fixation M5 sur la plaque verticale, centré entre les oreilles et à 22,00 mm du haut;
- bossage de réglage d'inclinaison : à 16,20 mm du haut de la plaque (donc
  plus bas, proche de la fenêtre CSI, pour un meilleur bras de levier), décalé
  de 8,00 mm sur le côté pour ne pas croiser le trou de fixation M5 central,
  au dos de la plaque, Ø 10,00 mm sur 6,00 mm de long, percé d'un trou taraudé
  M5 (Ø 4,20 mm) qui traverse tout le bossage et la plaque jusqu'à la face
  avant. La tige d'ajustement se visse dedans et sa bille appuie sur le dos
  de la caméra pour l'incliner autour de l'axe des oreilles quand on tourne
  la roue;
- fenêtre CSI dans la plaque verticale : 18,00 × 9,56 mm, centrée en bas et décalée vers l'avant.

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
4. Installer la caméra entre les oreilles avec l'axe M3 (pivot), sans la
   bloquer serrée pour qu'elle puisse encore pivoter.
5. Visser la tige d'ajustement (`adjustment_rod_M5x50_ball6.5_square_m3.stl`)
   dans le bossage taraudé M5 au dos de la plaque, bille côté caméra, jusqu'à
   ce qu'elle touche le dos de la caméra.
6. Clipser la roue (`wheel_crank_50mm_square_m3.stl`) sur le carré de la tige
   avec une vis M3 et tourner pour régler finement l'inclinaison; la caméra
   pivote autour de l'axe des oreilles.
7. Fixer la base par les deux rails inférieurs avec des vis M3.

Le profil d'impression détaillé est documenté dans
[`../../../materiel/README_support_camera_pi_pivot_reglable.md`](../../../materiel/README_support_camera_pi_pivot_reglable.md).
