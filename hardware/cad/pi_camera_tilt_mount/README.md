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
- `stl/camera_carrier_cover_v4_onepiece.stl` : **pièce 3 = ancien berceau 3 +
  ancien cache avant 4, en un seul solide fermé**, fusionnée dans la position
  assemblée (repère de `assemble.py`). Porte la carte Pi Camera Module 3
  (noir/NoIR, 25 × 24 mm, 4 trous Ø2,5 mm en carré 21 mm), se clipse entre les
  oreilles de la base sur l'axe M3 (tenon Ø 3,40 mm) et offre un patin plat au
  dos pour la bille de la tige. La carte **coulisse par le bas** dans une
  fente de 1,30 mm entre le berceau et le capot, jusqu'au pont du haut;
  l'objectif sort par l'ouverture Ø 11 mm. Les anciens fichiers
  `camera_carrier_v3_25x24_tab4.8.stl` et `camera_front_cover_v3_clip.stl`
  sont supprimés (obsolètes);
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

Numérotation du plan : 1 tige, 3 berceau + capot avant (pièce unique; l'ancien
4 est fusionné dans 3, numéro 4 retiré), 5 plaque-support à rotule (posée au dos de 3, bille de 1 dans sa douille),
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

## Cotes du berceau caméra (partie berceau de `camera_carrier_cover_v4_onepiece.stl`)

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

## Fusion 3 + 4 (capot intégré, `camera_carrier_cover_v4_onepiece.stl`)

Fusion faite dans les positions assemblées (mêmes coordonnées que
`assemble.py`). Vues avant/après dans `preview/` : `before_*.png` (3 et 4
séparés, ancien assemblage) et `assembly_*.png` (iso avant, iso arrière, côté,
dessus) où la zone bleu nuit « 3 (ex-4) » est l'ancien capot, jointe au
berceau (orange) par le pont du haut.

- capot : plaque 25,00 × 24,00 × 1,60 mm devant la carte, ouverture
  objectif Ø 11,00 mm (inchangée);
- fente carte : 1,30 mm (carte 1,20 + 0,10 de jeu), ouverte vers le bas et
  sur les côtés; le capot est décalé de 0,10 mm vers l'avant par rapport à
  l'ancien 4;
- pont de jonction : 25,00 × 1,50 mm au-dessus du bord haut de la carte
  (z = 32,21 → 33,71), du capot (y = −15,50) jusqu'au milieu du berceau
  (y = −11,60), posé sur le bord haut du berceau; il sert aussi de butée;
- 2 nervures de serrage 0,70 × 0,15 mm (x = ±12,05, hors carré de trous)
  qui maintiennent la carte par friction;
- les 4 pions de clip Ø 2,30 mm sont supprimés (ils empêchaient la carte de
  coulisser); les 4 trous Ø 2,50 mm du berceau sont conservés;
- inchangés : berceau 25 × ~29 × 2 mm, tenon 4,80 mm, trous d'axe, patin Ø 12
  × 0,6 mm, avant-trous M3 de la plaque 5, fente nappe. Emprise STL
  25,00 × 11,19 × 35,00 mm, un seul solide, volume ≈ 2202 mm³.

Pourquoi une fente coulissante et non une charnière souple : le capot est à
1,2 mm de la carte, une charnière PLA de cette taille casserait au premier
pliage; une fente à pont rigide s'imprime sans pièce fragile. La nappe CSI
se branche après avoir glissé la carte (connecteur accessible par la fente
traversante du berceau).
## Génération

Le générateur paramétrique `generate.py` dépend des bindings OpenCascade
fournis par le paquet `cadquery-ocp`. Dans un environnement Python dédié :

```bash
python3 -m pip install cadquery-ocp numpy
python3 hardware/cad/pi_camera_tilt_mount/generate.py
```

Exécuter la commande depuis la racine du dépôt. Elle vérifie les solides avant
l'export et remplace les STL listés ci-dessus.

## Réglages d'impression (matériau : Creality Hyper PLA blanc)

Imprimante : Creality Ender-3 S1 (Klipper). Un STL ne porte pas de réglages de
tranchage : ils sont donc (1) écrits dans l'en-tête binaire de 80 octets de
chaque STL (visible avec `head -c 80 fichier.stl`), par exemple
`Creality Hyper PLA blanc;N0.4 L0.2 I25% W4 T215/B60 V60;dos a plat;sup 55deg`
(buse, hauteur de couche, remplissage, parois, buse/lit °C, vitesse mm/s,
orientation, supports), et (2) détaillés pièce par pièce dans
[`print_settings.json`](print_settings.json) (source de vérité : orientation,
supports, tolérances de filetage M5 et d'emboîtement).

Valeurs communes : buse 0,4 mm, 215 °C (220 °C couche 1), lit 60 °C, ventilateur
0 % couche 1 puis 100 % dès la couche 3. Supports : toujours **arborescents
(tree)**, creux/légers (densité 8-10 %, interface fine d'1 couche, distance Z
0,16-0,22 mm, surplomb 55°), jamais sur les filetages — l'en-tête indique
`sup arbre` pour la base et le berceau. `generate.py`, `assemble.py` et
`stamp_stl_settings.py` réécrivent l'en-tête (STL binaires). `verify_stl.py`
vérifie que chaque en-tête contient « Creality Hyper PLA blanc » et ne commence
pas par `solid`. Aucun G-code n'est fourni ; les valeurs sont à reporter dans le
slicer.

## Impression et montage

1. Imprimer d'abord le test d'encombrement à plat et vérifier l'espace arrière.
2. Imprimer la pièce 3 debout sur son bord bas (supports arborescents légers sous le tenon, brim 3 mm conseillé), puis la base avec le grand dos de la plaque contre le plateau.
3. Supports **arborescents (tree)**, légers et faciles à retirer : angle de
   surplomb 55°, densité 8-10 %, interface fine d'1 couche à 10 %, distance Z
   0,22 mm (0,18 mm pour le berceau), appuis sur le plateau de préférence, jamais
   dans les filetages M5 ni les trous M3/Ø2,5 (les tiges et vis M5 sont
   imprimées debout, sans support). Retirer à la main ou à la pince fine.
4. Glisser la carte Pi Camera Module 3 par le bas dans la fente de la pièce 3
   (`camera_carrier_cover_v4_onepiece.stl`), objectif vers l'ouverture Ø 11 mm,
   jusqu'à la butée du pont; puis brancher la nappe CSI par la fente du berceau.
5. (étape supprimée : le cache 4 est intégré à 3.)6. Installer la pièce 3 (carte incluse) entre les oreilles de la base avec
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
