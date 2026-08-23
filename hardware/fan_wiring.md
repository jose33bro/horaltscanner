# Câblage ventilateur 24V - Horaltscanner

## Vue d'ensemble

Le ventilateur de refroidissement de la carte Creality V4.2.2 est alimenté en **24V DC**
et contrôlé par la broche **PC6 (PWM)** via un transistor ou relay.

## Spécifications du ventilateur

| Paramètre | Valeur |
|-----------|--------|
| Tension d'alimentation | 24V DC |
| Courant typique | 0.3A - 0.5A |
| Méthode de contrôle | PWM via relay ou MOSFET |
| Température de démarrage | 50°C (configurable dans `temperature_fan.cfg`) |
| Taille recommandée | 40x40mm ou 60x60mm |

---

## Schéma de câblage complet

### Avec transistor NPN (méthode recommandée)

```
Creality V4.2.2:
                     24V DC
                      │
                   [Fusible 2A]
                      │
                   ┌──┴──────────┐
                   │           [Diode 1N4007]
               [Ventilateur]   (cathode→+24V)
                   │           │
                   └──────┬────┘
                          │
                   [Collecteur NPN]
                          │
              PC6 ─[470Ω]─[Base NPN (2N2222)]
                          │
                   [Émetteur]
                          │
                         GND

Composants:
- Transistor NPN: 2N2222, BC547, ou TIP120 (pour ventilateurs > 500mA)
- Résistance base: 470Ω (ou 1K pour sécurité)
- Diode de roue libre: 1N4007 (OBLIGATOIRE - protège le transistor)
- Fusible: 2A rapide (protection alimentation)
```

### Avec relay 5V (méthode alternative)

```
Raspberry Pi 5V ──► Module relay 5V ──► Alimentation 24V ventilateur
PC6 ──► Signal de contrôle relay
GND ──► GND commun
```

---

## Connexion sur la carte Creality V4.2.2

Sur la Creality V4.2.2, le connecteur ventilateur principal est:

| Pin | Signal |
|-----|--------|
| + | 24V DC (contrôlé PWM PC6) |
| - | GND |

Le connecteur est marqué **"FAN"** sur la carte.

> **Note**: La broche PC6 génère un signal PWM. Le transistor ou relay
> convertit ce signal basse tension en commutation 24V pour le ventilateur.

---

## Configuration logicielle

La configuration du ventilateur est dans `klipper_config/temperature_fan.cfg`.

Pour modifier la température de déclenchement:

```ini
[temperature_fan board_fan]
target_temp: 50.0    # Température en °C pour démarrer le ventilateur
min_speed: 0.3       # Vitesse minimale (30%)
max_speed: 1.0       # Vitesse maximale (100%)
```

---

## Test du ventilateur

Dans la console Klipper (Mainsail/Fluidd):

```gcode
; Activer le ventilateur à pleine vitesse
FAN_ON

; Vérifier les températures
CHECK_TEMP

; Désactiver le ventilateur
FAN_OFF
```

---

## Notes de sécurité

- **Toujours installer la diode de roue libre** - sans elle, le transistor peut
  être détruit par les surtensions de la bobine du ventilateur
- Vérifier la polarité du ventilateur avant connexion
- Utiliser un câble de section min 0.5mm² pour 24V
