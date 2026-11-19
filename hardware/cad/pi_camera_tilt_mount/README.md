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
- `stl/camera_carrier_plate_v4_onepiece.stl` : **pièces 3 + 5 en un seul
  solide** (25,00 × 8,29 × 35,00 mm). Berceau qui porte la carte Pi
  Camera Module 3 (noir/NoIR, 25 × 24 mm, 4 trous Ø2,5 mm en carré 21 mm) et
  se clipse entre les oreilles de la base sur l'axe M3 (tenon Ø 3,40 mm), avec
  au dos l'ancienne plaque-support 5 fondue dedans (voir « Fusion 3 + 5 »);
- `stl/camera_front_cover_v3_clip.stl` : cache avant (côté objectif) qui
  tient la caméra sur le berceau sans vis — 4 pions se clipsent par
  pression dans les mêmes 4 trous Ø2,5 mm, en traversant la carte et le
  berceau, avec une ouverture centrale Ø11 mm pour l'objectif.

Les autres fichiers STL éventuellement présents dans ce répertoire ne sont pas
générés par `generate.py`.

Une pièce annexe est aussi générée par `generate.py` :

- `stl/ball_screw_M5x40_ball6.5.stl` : vis M5 × 0,8 (ISO pas normal), 40 mm,
  tête sphérique Ø 6,5 mm, fente de tournevis 0,8 × 5 × 1,5 mm. L'ancien STL ne
  contenait que la bille (tige absente).

Obsolètes et supprimés : `camera_carrier_v3_25x24_tab4.8.stl` (3),
`camera_support_plate_28.05x7x1.stl` (5) et son gabarit
`fit_test_plate_slot_28.45x7.4.stl`, remplacés par la pièce fusionnée.

## Fusion 3 + 5 (berceau + plaque-support)

La fusion est faite **dans la position assemblée** (repère de `assemble.py`,
`make_camera_carrier_with_plate()` dans `generate.py`) : la plaque 5 est
posée sur le dos du berceau (y = −10,6 mm, centrée sur l'axe M5, z = 16,2 mm),
douille à pétales vers +Y, puis fondue.

- Débord retiré : la plaque 5 faisait 28,05 mm de large pour 25,00 mm au
  berceau, soit 1,525 mm de trop de chaque côté ; elle est rognée à 25,00 mm
  (≈ 2 × 1,525 × 1 × 7 mm³ retirés, en rouge sur les vues `preview/`).
- Conservés tels quels : logement/trous caméra Ø2,5, rainure de nappe, tenon
  et trou d'axe M3 Ø3,4, trous M3 Ø3,2 (entraxe 14 mm) + avant-trous Ø2,7,
  douille Ø6,9 / lèvre Ø6,0 / passage de tige Ø5,3 / fentes 0,8.
- Seule modification : le patin du dos passe du rayon 6,00 à 3,50 mm (la bille
  n'y entre que par le passage Ø5,3) pour ne pas laisser un pont de 12 mm
  fermé sous la plaque (impression sans support dans une cavité).
- Orientation d'impression : à plat, face PCB sur le plateau, douille vers le
  haut (aucun support dans la douille).
- Vues avant/après : `preview/before_*.png` (3 et 5 séparées) et
  `preview/assembly_*.png` (fusionnée, zone ex-5 en jaune, débord retiré en
  rouge).

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

Numérotation du plan : 1 tige, 3+5 berceau et plaque-support à rotule (une
seule pièce imprimée, bille de 1 dans sa douille), 4 cache avant (clipsé sur
3), 8 base, 9 roue (sur le carré de 1). La tige 1 traverse le trou M5 de 8, 3
pivote sur les oreilles de 8 (axe M3, non modélisé). Filetages réels
M5 × 0,8 : tige à crête Ø 5,0 / noyau Ø 4,0 (thread 20 mm), trou de 8 alésé
Ø 5,5 avec filet interne de fond Ø 4,2 ; jeu radial 0,25 mm. Recouvrement
tige × base ≈ 0 mm³ (phase de vissage recherchée par `assemble.py`). Le carré de 1 (5 × 5 mm,
5 mm saillants) entre dans l'empreinte carrée du moyeu de 9 (5,2 × 5,2 mm,
6 mm de profondeur, moyeu 10 × 10 × 10 mm, vis M3 axiale Ø 3,2 mm), sans
recouvrement. Le contrôle de `assemble.py` vérifie que 3+5 est un seul
solide fermé de 25 mm de large, trous M3/tige ouverts et avant-trous aveugles.


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

## Cotes du berceau caméra (`camera_carrier_plate_v4_onepiece.stl`, partie 3)

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
- patin plat au dos : rayon 6,00 mm (3,50 mm sur la pièce fusionnée 3+5),
  profondeur 0,60 mm, où vient appuyer la bille de la tige. Une
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
2. Imprimer la base avec le grand dos de la plaque contre le plateau.
3. Supports **arborescents (tree)**, légers et faciles à retirer : angle de
   surplomb 55°, densité 8-10 %, interface fine d'1 couche à 10 %, distance Z
   0,22 mm (0,18 mm pour le berceau), appuis sur le plateau de préférence, jamais
   dans les filetages M5 ni les trous M3/Ø2,5 (les tiges et vis M5 sont
   imprimées debout, sans support). Retirer à la main ou à la pince fine.
4. Poser la carte Pi Camera Module 3 contre la face avant du berceau
   (`camera_carrier_plate_v4_onepiece.stl`), trous alignés.
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

## Cotes camera mesurees (Camera Module 3 NoIR Wide)

Mesurees au pied a coulisse (constantes de `generate.py`) :

| Constante | Valeur | Statut |
|---|---|---|
| `CAM_PCB_WIDTH` x `CAM_PCB_HEIGHT` | 25,16 x 24,16 mm | mesure |
| `CAM_TOTAL_THICKNESS` (carte + objectif) | 10,86 mm | mesure |
| `CAM_FIT_CLEARANCE_PER_SIDE` | 0,17 mm | jeu PLA choisi |
| `CAM_HOUSING_WIDTH` x `CAM_HOUSING_HEIGHT` | 25,50 x 24,50 mm | calcule (PCB + 2 x jeu) |
| `CAM_PCB_THICKNESS` (fente) | 1,20 mm | NON mesure, valeur conservee |
| `CAM_MOUNT_HOLE_SPACING` | 21,00 mm | NON mesure, doc officielle Camera Module 3 |
| `LENS_HOLE_DIAMETER` | 11,00 mm | objectif ~8,5 mm estime a l'oeil, non mesure |

La piece fusionnee 3+5 (et le capot 4, l'encoche de la base) utilisent maintenant
le logement 25,50 x 24,50 ; bbox fusionnee 25,50 x 8,29 x 35,00 mm. L'epaisseur totale
10,86 mm est enregistree mais la profondeur du logement n'est pas encore verifiee contre
le capot (non imprime).

### Epaisseurs camera mesurees (mise a jour)

| Constante | Valeur | Statut |
|---|---|---|
| `CAM_PCB_BARE_THICKNESS` | 1,06 mm | mesure (PCB nue) |
| `CAM_PCB_THICKNESS` (fente) | 1,26 mm | 1,06 + 0,20 de jeu |
| `CAM_COMPONENT_HEIGHT` | 4,25 mm | mesure (composants cote nappe/connecteur) |
| `CAM_TOTAL_THICKNESS` | 10,86 mm | mesure (avec objectif) |

Le capot 4 passe a 4,56 mm de profondeur (fente 1,26). Le degagement composants
(4,25 + 0,3) est une constante prevue mais pas encore sculptee dans la geometrie.

### Languette nappe FFC (mesuree)

`CAM_FFC_WIDTH` 7,43 mm et `CAM_FFC_THICKNESS` 0,82 mm (pied a coulisse, a cote de l'objectif ;
interpretation "languette FFC" NON confirmee). Utilisees pour la rainure de nappe du berceau
3+5 : largeur requise 7,43 + 0,30 = 7,73 mm (canal garde a 16 mm, impose par `CABLE_PASSAGE_WIDTH`
de la tablette) ; profondeur `CARRIER_CABLE_CHANNEL_DEPTH` = 0,82 + 0,20 = 1,02 mm (avant 0,60).

`CAM_FFC_LENGTH` 8,88 mm (+ 0,30 de jeu = 9,18 mm) : la rainure de nappe s'etend maintenant
de 4,59 mm (= 9,18 / 2) au-dessus du centre du connecteur (avant 3,00 mm), soit +1,59 mm.

`CAM_FFC_CONNECTOR_HEIGHT` 2,45 mm (hauteur du connecteur FFC cote composants, interpretation de
"epaisseur nappe 2,45") + 0,30 = `CAM_FFC_CONNECTOR_RELIEF` 2,75 mm requis. Une fenetre traversante
de 7,73 mm de large est ouverte dans le berceau (2 mm d'epaisseur) au droit du connecteur, de la
fente basse jusqu'a 1 mm sous la poche de rotule (z ~ 11,7). Les 2,75 mm ne tiennent pas dans 2 mm :
la fenetre est bornee par la plaque 5 fusionnee derriere (non creusee). Le reste des composants
garde 4,25 mm (`CAM_COMPONENT_HEIGHT`). La mesure ~20,9 mm lue sur photo est ignoree.

### Entraxe X mesure et largeur connecteur (20,87 mm)

`CAM_MOUNT_HOLE_SPACING_X` = 20,87 mm (mesure, remplace 21 sur l'axe X) ; l'entraxe Z reste 21,00
(doc officielle, non mesure). `CAM_FFC_CONNECTOR_WIDTH` = 20,87 mm est enregistre mais NON applique a
la fente : 20,87 + 0,30 = 21,17 mm depasserait l'entraxe des trous M3 (meme cote) et les fusionnerait
avec la fente. La fente reste a 16 mm (fenetre 7,73 mm). A confirmer : cette cote est probablement
l'entraxe des trous et non la largeur du connecteur.

### Entraxe Z mesure (12,33 mm) - remplace les mentions "Z = 21 mm" ci-dessus

`CAM_MOUNT_HOLE_SPACING` = 12,33 mm (mesure approximative du user ; doc officielle : 12,5 mm).
Le modele utilisait a tort 21 mm (motif carre) sur Z. Motif de trous : 20,87 (X) x 12,33 (Z).
Le centre du motif est inchange, donc contour PCB, capot et nappe ne bougent pas ; seuls les
trous/pions du berceau et du capot se rapprochent (z ~ 14,0 et 26,4).

### Origine des valeurs camera (reference ; remplace les sections precedentes sur les entraxes)

Decision du user : les entraxes de trous suivent la doc officielle (plus precise), pas le pied a coulisse.

| Valeur | Source |
|---|---|
| Entraxe trous X x Z : 21,00 x 12,50 mm (`CAM_MOUNT_HOLE_SPACING_X`, `CAM_MOUNT_HOLE_SPACING`) | doc officielle |
| Carte 25,16 x 24,16 ; epaisseur totale 10,86 ; PCB nue 1,06 ; composants 4,25 | pied a coulisse |
| Languette FFC 7,43 x 8,88 x 0,82 ; hauteur connecteur 2,45 | pied a coulisse |
| 20,87 mm (`CAM_FFC_CONNECTOR_WIDTH`) | pied a coulisse, enregistre seulement |
| Jeux (0,17 / 0,20 / 0,30), fente PCB 1,26, objectif Ø11 | choix de conception / estimation |

Les mentions "20,87 x 12,33" ci-dessus sont obsoletes : le motif de trous est 21,00 x 12,50 mm.

### Fenetre objectif du capot 4

`LENS_BARREL_SIZE` 8,50 mm (estime a l'oeil, NON mesure) + 2 x `LENS_CLEARANCE_PER_SIDE` 0,45
= `LENS_HOLE_DIAMETER` 9,40 mm (avant : 11,00). Centre : centre du motif de trous (21 x 12,5, doc)
+ `LENS_OFFSET_X` / `LENS_OFFSET_Z` (0 / 0 par defaut, hypothese, a regler a la main : la position
reelle de l'axe optique n'est pas mesuree). Hauteur totale 10,86 mm non utilisee ici.

## Volets « barn doors » (pièce 4 + 2 plaques X + 2 plaques Z)

**Faisabilité** : la paroi du capot (1,6 mm) est trop fine pour des rainures, et l'objectif dépasse d'environ 8,0 mm de la face avant. Les volets doivent être devant la lentille pour cadrer. Le capot reçoit donc un fourreau creux (profondeur 8,5 mm) puis un cadre à deux couches de fentes (volets gauche/droite derrière, haut/bas devant).

- Constantes dans `generate.py` : `DOOR_THICKNESS` 0,9, `DOOR_SLOT_CLEARANCE` 0,2, `DOOR_TRAVEL_X` 9, `DOOR_TRAVEL_Z` 8,5, `FRAME_BORE_WIDTH/HEIGHT` 18 × 17, `HOOD_STANDOFF_DEPTH` 8,5.
- STL séparés, à plat, sans supports : `camera_barn_door_x_x2.stl` (10 × 19 × 0,9, imprimer 2) et `camera_barn_door_z_x2.stl` (20 × 10 × 0,9, imprimer 2).
- Capot : bbox 25,50 × 16,86 × 24,50 mm ; imprimé bout du cadre à plat, pions vers le haut.
- Non vérifié : impression, friction des volets, ponts courts des fentes, vignettage du cadre sur les coins du champ ~120° (H 102°, V 67°). Pas de vis M3 / trous oblongs (glissement par friction seulement).
