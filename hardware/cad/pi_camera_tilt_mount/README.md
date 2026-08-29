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
- fenêtre CSI fermée dans la plaque: 18,00 × 9,56 mm.

Les oreilles sont centrées en haut de la plaque de 38,20 mm. Le support de
caméra entre dans leur espace de 5,33 mm. Une seule vis M3 traverse les deux
arrondis et le support; un écrou M3 bloque l'angle. La nappe CSI traverse la
fenêtre centrale sans ouverture jusqu'au bord de la pièce.

## Fichiers

- `stl/fit_test_rear_cavity_30.45x38.2.stl`: test d'encombrement à imprimer en
  premier;
- `stl/pi_camera_tilt_base.stl`: base orientable définitive;
- `generate.py`: source paramétrique Python/OpenCascade.

## Visserie

- 1 vis M3 traversante avec écrou et 2 rondelles pour le pivot caméra;
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
