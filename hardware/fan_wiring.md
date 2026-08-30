# Câblage ventilateur 24V - Horaltscanner

## Ventilateur du Raspberry Pi (GPIO23)

Le ventilateur de refroidissement du Raspberry Pi est distinct du ventilateur
24V de la carte Creality. Le service HoralScanner le commande en tout-ou-rien
sur **GPIO23** (broche physique 16): `1` l'active et `0` le désactive.

Le service lit `/sys/class/thermal/thermal_zone0/temp` toutes les 5 secondes:

- démarrage du ventilateur à 55°C;
- arrêt à 45°C;
- maintien de l'état entre 45°C et 55°C pour éviter les commutations rapides;
- activation de sécurité si la température CPU ne peut pas être lue.

```text
GPIO23 ──[1 kΩ]── Gate MOSFET logique
GND Pi ────────── Source MOSFET
Drain MOSFET ──── Ventilateur -
5V Pi ─────────── Ventilateur +
```

Ne jamais alimenter le ventilateur directement depuis GPIO23. Utiliser un
MOSFET logique et une diode de roue libre, avec une masse commune.

Test via l'API:

```bash
curl -X POST http://localhost:5000/api/fan/pi \
  -H 'Content-Type: application/json' \
  -d '{"percent":100}'
```

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

La configuration du ventilateur est gérée par l'API HoralScanner via `software/api/horalscanner_api.py`.

Pour modifier la température de déclenchement, éditer `config/horalscanner_config.json`.

---

## Test du ventilateur

Via l'API REST:

```bash
# Activer le ventilateur Pi à 50%
curl -X POST http://localhost:5000/api/fan/pi -H "Content-Type: application/json" -d '{"percent": 50}'

# Vérifier les températures
curl http://localhost:5000/api/temperature/all

# Désactiver le ventilateur
curl -X POST http://localhost:5000/api/fan/pi -H "Content-Type: application/json" -d '{"percent": 0}'
```

---

## Notes de sécurité

- **Toujours installer la diode de roue libre** - sans elle, le transistor peut
  être détruit par les surtensions de la bobine du ventilateur
- Vérifier la polarité du ventilateur avant connexion
- Utiliser un câble de section min 0.5mm² pour 24V
