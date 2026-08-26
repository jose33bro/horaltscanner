# Support orientable pour Pi Camera V3

Ce modèle réutilise le berceau blanc visible sur le scanner. La nouvelle base
occupe l'espace libre derrière ce berceau et place ses deux trous latéraux sur
un axe de rotation M3.

## Cotes utilisées

- espace arrière disponible: 53,44 × 31,70 × 16,03 mm;
- base avec jeu d'impression: 52,80 × 15,50 mm;
- deux avant-trous latéraux de 2,70 mm, profondeur 10 mm, pour vis M3;
- centre des trous: 26,42 mm au-dessus du bas de la languette;
- trous existants: 5,1 mm;
- largeur du berceau: 32,14 mm.

La profondeur utile autorise environ 27° théoriques. Le réglage conseillé est
limité à 23° vers l'intérieur afin de conserver du jeu autour du berceau.
La nappe CSI reste en dehors de cette base et ne traverse donc plus la pièce.

## Fichiers

- `stl/fit_test_rear_cavity_52.8x15.5.stl`: test d'encombrement à imprimer en
  premier;
- `stl/pi_camera_tilt_base.stl`: base orientable définitive;
- `generate.py`: source paramétrique Python/OpenCascade.

## Visserie

- 2 vis M3;
- 2 écrous M3;
- 4 rondelles M3.
- 2 vis M3 supplémentaires de 10 à 12 mm pour fixer la base au support rouge.

Les rondelles doivent couvrir les trous de 5,1 mm du berceau blanc. Les deux
vis serrent les flancs de la base contre le berceau afin de bloquer l'angle.

## Impression et montage

1. Imprimer d'abord le test d'encombrement à plat.
2. Vérifier qu'il entre dans l'espace arrière sans forcer. Ajuster les
   constantes `BASE_WIDTH` et `BASE_DEPTH` si nécessaire.
3. Imprimer la base définitive dans la même orientation, en PETG recommandé,
   avec quatre périmètres et au moins 35 % de remplissage.
4. Retirer le berceau blanc du support rouge sans débrancher brutalement la
   nappe CSI.
5. Placer le berceau entre les deux flancs, aligner les trous et installer la
   visserie M3 avec les rondelles.
6. Placer la nouvelle base derrière le berceau, régler l'inclinaison entre 0 et
   23° vers l'intérieur, puis serrer les deux vis.
7. Repérer les deux avant-trous latéraux, percer le support rouge à 3,2 mm puis
   fixer la base depuis chaque côté avec une vis M3 de 10 à 12 mm.

Maintenir la nappe CSI à l'extérieur de la base. Ne pas la pincer ni la plier
fortement pendant l'inclinaison.
