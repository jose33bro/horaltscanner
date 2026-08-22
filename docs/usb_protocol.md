# Protocole USB (Raspberry Pi ↔ Creality V4.2.2)

Transport attendu: USB CDC (liaison série virtuelle).

## Commandes

1. `PING`
   - Réponse: `OK PONG`

2. `MOVE <AXIS> <STEPS> <SPEED>`
   - `AXIS`: `X`, `Y`, `Z`
   - Réponse: `OK MOVE`

3. `HOME Y`
   - Référence Y au point 0 (endstop côté lidar TF-Luna)
   - Réponse: `OK HOME`

4. `ENDSTOP Y`
   - Réponse: `OK ENDSTOP 0` ou `OK ENDSTOP 1`

5. `SYNC <TOKEN>`
   - Barrière de synchronisation moteurs/capteurs
   - Réponse: `OK SYNC <TOKEN>`
