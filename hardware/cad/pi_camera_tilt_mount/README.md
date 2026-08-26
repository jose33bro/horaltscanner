# Support orientable pour Pi Camera V3

Ce modèle réutilise le berceau blanc visible sur le scanner. La nouvelle base
occupe l'espace libre derrière ce berceau et place ses deux trous latéraux sur
un axe de rotation M3.

## Cotes utilisées

- base corrigée après essai imprimé: 38,20 × 30,45 mm;
- deux avant-trous latéraux de 2,70 mm, profondeur 10 mm, pour vis M3;
- deux parois latérales: longueur 24,00 mm, hauteur 6,20 mm;
- deux oreilles centrales: longueur 8,70 mm, hauteur 5,99 mm;
- espace entre les oreilles: 5,33 mm;
- largeur de la fixation sous la caméra: 16,90 mm;
- trou traversant M3: 3,40 mm.

Le support de caméra entre dans l'espace de 5,33 mm entre les oreilles. Une
seule vis M3 traverse les deux oreilles et le support; un écrou M3 bloque
l'angle. La nappe CSI reste en dehors de cette base.

## Fichiers

- `stl/fit_test_rear_cavity_38.2x30.45.stl`: test d'encombrement à imprimer en
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
2. Vérifier qu'il entre dans l'espace arrière sans forcer. Ajuster les
   constantes `BASE_WIDTH` et `BASE_DEPTH` si nécessaire.
3. Imprimer la base définitive dans la même orientation, en PETG recommandé,
   avec quatre périmètres et au moins 35 % de remplissage.
4. Retirer le berceau blanc du support rouge sans débrancher brutalement la
   nappe CSI.
5. Placer la patte du support caméra dans l'espace central de 5,33 mm.
6. Aligner les trous, installer la vis M3 traversante, régler l'inclinaison et
   serrer l'écrou.
7. Repérer les deux avant-trous latéraux, percer le support rouge à 3,2 mm puis
   fixer la base depuis chaque côté avec une vis M3 de 10 à 12 mm.

Maintenir la nappe CSI à l'extérieur de la base. Ne pas la pincer ni la plier
fortement pendant l'inclinaison.
