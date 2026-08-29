# Support orientable pour Pi Camera V3

Ce modèle en L réutilise le support blanc visible sur le scanner. Sa plaque
verticale reprend l'espace validé, tandis qu'une tablette inférieure part vers
l'avant. Deux oreilles arrondies en haut reçoivent l'axe M3 de la caméra.

## Cotes utilisées

- plaque verticale corrigée après essai: 30,45 × 38,20 × 3,20 mm;
- tablette inférieure vers l'avant: 24,00 mm;
- deux parois sur les côtés de la tablette: hauteur 6,20 mm;
- deux rails sous la tablette, depuis le bord avant: largeur 5,00 mm, longueur
  16,00 mm, descente 5,00 mm;
- un avant-trou horizontal de 2,70 mm dans chaque rail pour une vis M3 depuis
  le côté;
- deux oreilles arrondies sortant du bord avant: projection 8,70 mm, largeur
  8,50 mm, hauteur 5,99 mm;
- espace entre les oreilles: 5,33 mm;
- trou traversant M3: 3,40 mm.
- hauteur totale caméra + support entre les oreilles: 34,00 mm;
- trou de réglage inférieur orienté arrière → avant dans la plaque verticale:
  M5 (Ø 5,30 mm de passage); position remontée de 5 mm par rapport au placement
  précédent;
- vis de réglage inférieure: M5 à bout sphérique, longueur utile 40 mm,
  boule Ø 6,5 mm au bout (le diamètre de la boule est inférieur au passage M5
  de 5,3 mm + chanfrein d'entrée);
- logement de la boule côté support caméra: Ø 6,9 mm (hémisphère centré sur la plaque);
- fenêtre CSI centrée dans la tablette horizontale: 18,00 × 9,56 mm.

Les oreilles sont centrées en haut de la plaque (hauteur 38,20 mm). Le support de
caméra entre dans leur espace de 5,33 mm. Une seule vis M3 traverse les deux
arrondis et le support; un écrou M3 bloque l'angle. La vis inférieure de
réglage M5 à bout sphérique (longueur 40 mm, boule Ø 6,5 mm) traverse maintenant
la plaque verticale d'arrière → avant, avec un passage imprimable de 5,30 mm.
Le trou de réglage a été remonté de 5 mm par rapport au placement précédent.
La nappe CSI traverse la fenêtre centrée dans la tablette horizontale.
La boule de bout est reçue dans le logement Ø 6,9 mm centré sur la plaque support
(28,05 × 7 × 1 mm); un trou M3 permet la fixation du support caméra.

## Fichiers

- `stl/fit_test_rear_cavity_30.45x38.2.stl`: test d'encombrement à imprimer en
  premier;
- `stl/pi_camera_tilt_base.stl`: base orientable définitive;
- `stl/ball_screw_M5x40_ball6.5.stl`: vis M5 × 40 mm à bout sphérique Ø 6,5 mm;
- `stl/camera_support_plate_28.05x7x1.stl`: plaque support caméra 28,05 × 7 × 1 mm
  avec logement boule Ø 6,9 mm centré et trou M3;
- `generate.py`: source paramétrique Python/OpenCascade.

## Visserie

- 1 vis M3 traversante avec écrou et 2 rondelles pour le pivot caméra;
- 1 vis M5 × 40 mm à bout sphérique Ø 6,5 mm pour le réglage inférieur;
- 2 vis M3 supplémentaires de 10 à 12 mm pour fixer la base au support rouge.

La vis traversante serre les deux oreilles contre la patte centrale du support
caméra afin de bloquer l'angle.

## Impression et montage

1. Imprimer d'abord le test d'encombrement à plat.
2. Vérifier qu'il correspond à l'espace arrière sans forcer.
3. Imprimer la base définitive en PETG recommandé,
   avec quatre périmètres et au moins 35 % de remplissage.
4. Retirer le berceau blanc du support rouge sans débrancher brutalement la
   nappe CSI.
5. Placer la patte du support caméra dans l'espace central de 5,33 mm.
6. Aligner les trous, installer la vis M3 traversante, régler l'inclinaison et
   serrer l'écrou.
7. Repérer les deux avant-trous dans les rails inférieurs, percer le support
   rouge à 3,2 mm puis fixer la base horizontalement depuis chaque côté avec
   une vis M3.

Maintenir la nappe CSI à l'extérieur de la base. Ne pas la pincer ni la plier
fortement pendant l'inclinaison.
