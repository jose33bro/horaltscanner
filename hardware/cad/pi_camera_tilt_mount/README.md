# Support orientable pour Pi Camera V3

Ce modèle réutilise le berceau blanc visible sur le scanner. La nouvelle base
s'emboîte à sa place dans le support rouge et place les deux trous latéraux du
berceau sur un axe de rotation.

## Cotes utilisées

- languette blanche mesurée: 27,89 × 7,55 mm;
- insertion actuelle: 16,08 mm;
- centre des trous: 26,42 mm au-dessus du bas de la languette;
- trous existants: 5,1 mm;
- largeur du berceau: 32,14 mm.

La languette imprimée mesure 27,6 × 7,3 mm pour laisser environ 0,3 mm de jeu
sur une imprimante FDM. Un passage central de 18 mm, ouvert vers l'avant,
laisse descendre la nappe CSI à l'intérieur du support rouge sans la pincer.

## Fichiers

- `stl/fit_test_27.6x7.3.stl`: petit test d'emboîtement à imprimer en premier;
- `stl/pi_camera_tilt_base.stl`: base orientable définitive;
- `generate.py`: source paramétrique Python/OpenCascade.

## Visserie

- 2 vis M3;
- 2 écrous M3;
- 4 rondelles M3.

Les rondelles doivent couvrir les trous de 5,1 mm du berceau blanc. Les deux
vis serrent les flancs de la base contre le berceau afin de bloquer l'angle.

## Impression et montage

1. Imprimer d'abord le test d'emboîtement, languette vers le plateau.
2. Vérifier qu'il entre dans le support rouge sans forcer. Ajuster les
   constantes `TONGUE_WIDTH` et `TONGUE_DEPTH` si nécessaire.
3. Imprimer la base définitive dans la même orientation, en PETG recommandé,
   avec quatre périmètres et au moins 35 % de remplissage.
4. Retirer le berceau blanc du support rouge sans débrancher brutalement la
   nappe CSI.
5. Placer le berceau entre les deux flancs, aligner les trous et installer la
   visserie M3 avec les rondelles.
6. Emboîter la nouvelle base dans le support rouge, régler l'inclinaison puis
   serrer les deux vis.

Faire passer la nappe CSI dans l'ouverture centrale avant d'emboîter la base.
Ne pas pincer ni plier fortement la nappe pendant l'inclinaison.
