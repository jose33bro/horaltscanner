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
  carré de montage et trou M3 central pour serrage sur plaque de 3 mm;
- `stl/camera_carrier_v3_25x24_tab4.8.stl` : berceau qui porte la carte Pi
  Camera Module 3 (noir/NoIR, 25 × 24 mm, 4 trous Ø2,5 mm en carré 21 mm) et
  se clipse entre les oreilles de la base sur l'axe M3 (tenon Ø 3,40 mm), avec
  un patin plat au dos où vient appuyer la bille de la tige d'ajustement;
- `stl/camera_front_cover_v3_clip.stl` : cache avant (côté objectif) qui
  tient la caméra sur le berceau sans vis — 4 pions se clipsent par
  pression dans les mêmes 4 trous Ø2,5 mm, en traversant la carte et le
  berceau, avec une ouverture centrale Ø11 mm pour l'objectif.

Les autres fichiers STL éventuellement présents dans ce répertoire ne sont pas
générés par `generate.py`.

Trois pièces annexes sont aussi générées par `generate.py` :

- `stl/ball_screw_M5x40_ball6.5.stl` : vis M5 × 0,8 (ISO pas normal), 40 mm,
  tête sphérique Ø 6,5 mm, fente de tournevis 0,8 × 5 × 1,5 mm. L'ancien STL ne
  contenait que la bille (tige absente) ;
- `stl/camera_support_plate_28.05x7x1.stl` : plaque 28,05 × 7 × 1 mm, deux
  trous M3 Ø 3,2 mm sur entraxe 14 mm (cote de `hardware/mechanical_specs.md`;
  l'ancien STL utilisait 16 mm), douille Ø 6,9 mm à 4 pétales (fentes 0,8 mm,
  lèvre Ø 6,0 mm qui verrouille la bille de 6,5 mm) et passage de tige Ø 5,3 mm;
- `stl/fit_test_plate_slot_28.45x7.4.stl` (ex `fit_test_27.6x7.3.stl`, bloc
  33,6 × 13,3 × 8 mm) : gabarit à poche 28,45 × 7,40 mm = plaque + 0,2 mm par
  côté. L'ancienne poche de 27,6 mm était plus courte que la plaque (28,05 mm).

Chaque STL est vérifié à l'export (maillage fermé, sans triangle dégénéré) et
`verify_stl.py` contrôle en plus l'encombrement attendu :

```bash
python3 hardware/cad/pi_camera_tilt_mount/verify_stl.py
```

## Assemblage complet (`assemble.py`)

`assemble.py` place toutes les pièces dans un seul repère et exporte
`stl/assembly_pi_camera_tilt_mount.stl`, des vues dans `preview/` et un
contrôle d'interférence (intersections booléennes deux à deux) :

```bash
python3 -m pip install numpy trimesh manifold3d matplotlib
python3 hardware/cad/pi_camera_tilt_mount/assemble.py
```

Numérotation du plan : 1 tige, 3 berceau, 4 cache avant (clipsé sur 3),
5 plaque-support à rotule (posée au dos de 3, bille de 1 dans sa douille),
8 base, 9 roue (sur le carré de 1). La tige 1 traverse le trou M5 de 8, 3
pivote sur les oreilles de 8 (axe M3, non modélisé). Filetages réels
M5 × 0,8 : tige à crête Ø 5,0 / noyau Ø 4,0 (thread 20 mm), trou de 8 alésé
Ø 5,5 avec filet interne de fond Ø 4,2 ; jeu radial 0,25 mm. Recouvrement
tige × base ≈ 0 mm³ (phase de vissage recherchée par `assemble.py`). Le carré de 1 (5 × 5 mm,
5 mm saillants) entre dans l'empreinte carrée du moyeu de 9 (5,2 × 5,2 mm,
6 mm de profondeur, moyeu 10 × 10 × 10 mm, vis M3 axiale Ø 3,2 mm), sans
recouvrement. La plaque 5 est vissée à plat au dos du berceau 3 par deux
vis M3 (entraxe 14 mm, avant-trous Ø 2,7 mm ajoutés au berceau dans
`generate.py`) ; le contrôle vérifie contact à 0 mm et trous alignés.


- plaque verticale : 30,45 × 38,20 × 3,20 mm;
- tablette inférieure vers l'avant : projection 24,00 mm;
- parois latérales de tablette : 3,20 mm d'épaisseur et 6,20 mm de hauteur;
- rails sous la tablette : 5,00 mm de large, 16,00 mm de long et 5,00 mm de
  descente, avec un avant-trou horizontal Ø 2,70 mm dans chaque rail et une
  découpe de 3,00 mm depuis l'avant pour dégager le passage M3;
- passage de nappe du câble CSI dans la partie tablette : ouverture centrale
  vers l'avant, dans la tablette de 24,00 mm.
- oreilles : projection 8,70 mm, largeur 8,50 mm, hauteur 5,99 mm et espace
  central 5,33 mm;
- trou d'axe traversant : Ø 3,40 mm;
- trou de fixation M5 sur la plaque verticale, centré entre les oreilles et à 22,00 mm du haut;
- fenêtre CSI dans la plaque verticale : 18,00 × 9,56 mm, centrée en bas et décalée vers l'avant;
- encoches de dégagement dans les parois latérales de la tablette (côté
  intérieur) là où la carte caméra (25,00 mm de large) est plus large que
  l'écart utile entre parois (24,05 mm);
- poche de dégagement dans la face supérieure de la tablette, sous la zone
  balayée par le bord bas du berceau pendant le pivotement (voir plage de
  réglage ci-dessous) : sans elle, le berceau coince contre la tablette dès
  une fraction de degré dans un des deux sens de rotation.

## Plage de réglage de l'inclinaison

Le berceau pivote autour de l'axe M3 des oreilles; au repos (0°) il touche
la tablette, qui sert de butée naturelle d'un côté. La plage utile réelle,
vérifiée géométriquement (volumes de recouvrement nuls entre solides), est
**-15° à +9°** par rapport au repos :

- jusqu'à -15° : dégagement complet, aucun contact parasite;
- au-delà de +9° : le berceau commence à empiéter dans la fenêtre CSI de la
  plaque verticale (pas un contact matière, mais un risque de pincer la
  nappe du câble CSI qui passe par cette fenêtre).

Cette plage asymétrique convient à l'usage prévu : la caméra est déjà
orientée vers le bas (vers le plateau tournant) au repos, donc le sens
disponible le plus large (-15°, qui l'incline encore plus vers le bas) est
celui qui compte le plus.

## Cotes du berceau caméra (`camera_carrier_v3_25x24_tab4.8.stl`)

- plaque porte-caméra : 25,00 × ~29,00 × 2,00 mm (hauteur ajustée pour
  rejoindre le bas des oreilles), espacée de 9,00 mm derrière la face avant
  de la plaque principale (jeu pour la tige d'ajustement et pour que le
  bord bas du berceau dégage la plaque sur toute la plage de réglage);
- 4 trous de fixation M2/M2,5 Ø 2,50 mm en carré de 21,00 mm, cotes
  officielles du Camera Module 3 (25 × 24 mm, standard ou NoIR);
- tenon de charnière : largeur 4,80 mm (jeu dans l'espace de 5,33 mm entre
  les oreilles), même profil arrondi que les oreilles, trou d'axe Ø 3,40 mm
  aligné avec celui de la base; profondeur dimensionnée pour ne chevaucher
  que la propre plaque du berceau (fusion solide), sans jamais pénétrer
  dans la plaque principale;
- patin plat au dos (remplace l'ancienne fossette sphérique) : rayon
  6,00 mm, profondeur 0,60 mm, où vient appuyer la bille de la tige. Une
  sphère contre un plan garde un contact valide à n'importe quel angle,
  contrairement à une fossette sphérique de même rayon que la bille, dont
  la plage utile ne dépassait que ±2,4° avant perte de contact.

## Cotes du cache avant (`camera_front_cover_v3_clip.stl`)

- plaque : 25,00 × 24,00 × 1,60 mm, plaquée contre la face avant de la carte
  caméra (côté objectif);
- ouverture centrale Ø 11,00 mm, centrée sur le carré de trous de montage,
  pour dégager l'objectif;
- 4 pions de clipsage Ø 2,30 mm (léger serrage dans les trous Ø 2,50 mm de
  la carte), longueur de pénétration ~2,90 mm (épaisseur carte + berceau,
  sans atteindre la face arrière du berceau), pointe conique de 0,80 mm pour
  faciliter l'insertion. Remplace les vis/écrous M2,5 : pousser le cache en
  face, les pions traversent la carte et se bloquent par friction dans les
  trous du berceau.

## Génération

Le générateur paramétrique `generate.py` dépend des bindings OpenCascade
fournis par le paquet `cadquery-ocp`. Dans un environnement Python dédié :

```bash
python3 -m pip install cadquery-ocp numpy
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

Exécuter la commande depuis la racine du dépôt. Elle vérifie les solides avant
l'export et remplace les six STL listés ci-dessus.

## Impression et montage

1. Imprimer d'abord le test d'encombrement à plat et vérifier l'espace arrière.
2. Imprimer la base avec le grand dos de la plaque contre le plateau.
3. Utiliser des supports « Everywhere », angle de surplomb 55°, densité 12 %,
   interface activée (2 couches) et distance Z de 0,22 mm.
4. Poser la carte Pi Camera Module 3 contre la face avant du berceau
   (`camera_carrier_v3_25x24_tab4.8.stl`), trous alignés.
5. Clipser le cache avant (`camera_front_cover_v3_clip.stl`) par-dessus : les
   4 pions traversent les trous de la carte et se bloquent par pression dans
   les trous du berceau — pas de vis ni d'écrou nécessaires.
6. Installer le berceau (carte + cache) entre les oreilles de la base avec
   l'axe M3 (pivot), sans le bloquer serré pour qu'il puisse encore pivoter.
7. Visser la tige d'ajustement (`adjustment_rod_M5x50_ball6.5_square_m3.stl`)
   dans le bossage taraudé M5 au dos de la plaque, bille côté caméra, jusqu'à
   ce qu'elle appuie contre le patin plat au dos du berceau.
8. Clipser la roue (`wheel_crank_50mm_square_m3.stl`) sur le carré de la tige
   avec une vis M3 et tourner pour régler finement l'inclinaison (plage
   utile -15°/+9°, voir « Plage de réglage de l'inclinaison » plus haut); le
   berceau pivote autour de l'axe des oreilles.
9. Fixer la base par les deux rails inférieurs avec des vis M3.

Le profil d'impression détaillé est documenté dans
[`../../../materiel/README_support_camera_pi_pivot_reglable.md`](../../../materiel/README_support_camera_pi_pivot_reglable.md).
