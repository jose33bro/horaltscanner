# Protocole USB (Raspberry Pi ↔ Creality V4.2.2)

Transport attendu: USB CDC (liaison série virtuelle).

## Commandes

1. `PING`
   - Réponse: `OK PONG`

2. `MOVE <AXIS> <STEPS> <SPEED>`
   - `AXIS`: `X`, `Y`, `Z`
   - Réponse: `OK MOVE`

3. `HOME <AXIS>`
   - `AXIS`: `X`, `Y`, `Z` ou `ALL`.
   - Référence l'axe demandé sur son endstop.
   - Réponse: `OK HOME`

4. `ENDSTOP Y`
   - Réponse: `OK ENDSTOP 0` ou `OK ENDSTOP 1`

5. `SYNC <TOKEN>`
   - Barrière de synchronisation moteurs/capteurs
   - `TOKEN` ne doit pas contenir d'espaces
   - Réponse: `OK SYNC <TOKEN>`

6. `STOP <AXIS>`
   - `AXIS`: `X`, `Y`, `Z` ou `ALL`.
   - Arrête immédiatement l'axe demandé.
   - Réponse: `OK STOP`

7. `FAN_PA0_PWM <VALUE>`
   - Commande le ventilateur Creality sur PA0.
   - `VALUE`: entier de 0 à 255.
   - Réponse: `OK FAN_PA0_PWM`

8. `FAN_PA8_PWM <VALUE>`
   - Commande le ventilateur de température sur PA8.
   - `VALUE`: entier de 0 à 255.
   - Réponse: `OK FAN_PA8_PWM`

9. `TEMP_PC5_READ`
   - Lit la thermistance EPCOS 100K B57560G104F raccordée à l'ADC PC5.
   - Réponse: `OK TEMP_PC5 <CELSIUS>`, par exemple `OK TEMP_PC5 42.6`.
   - Le firmware STM32 effectue la conversion ADC vers degrés Celsius.
