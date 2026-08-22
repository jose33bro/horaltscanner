# Schéma de câblage - Horaltscanner

## Vue d'ensemble du système

```
┌───────────────────────────────────────────────────────────────┐
│                    HORALTSCANNER                              │
│                                                               │
│  ┌─────────────────┐         ┌──────────────────────────┐    │
│  │  Raspberry Pi 4 │         │  Creality V4.2.2          │    │
│  │  (4 Go RAM)     │◄──USB──►│  STM32F103RET6            │    │
│  │                 │         │                           │    │
│  │  GPIO17 ────────┼── Laser gauche (5V TTL → relay)    │    │
│  │  GPIO27 ────────┼── Laser droit  (5V TTL → relay)    │    │
│  │  DSI      ──────┼── Caméra Pi V3 Noir                │    │
│  │  USB      ──────┼── Caméra Logitech USB              │    │
│  │  USB      ──────┼── Lidar TF-Luna                    │    │
│  └─────────────────┘         │                           │    │
│                              │  PA0 (ADC) ── Thermostat  │    │
│                              │  PC6 (PWM) ── Ventilateur │    │
│                              │  PB9/PC2 ──── Moteur X    │    │
│                              │  PB7/PB8 ──── Moteur Y    │    │
│                              │  PB5/PB6 ──── Moteur Z    │    │
│                              │  PA5 ───────── Endstop X  │    │
│                              │  PA6 ───────── Endstop Y  │    │
│                              │  PA7 ───────── Endstop Z  │    │
│                              └──────────────────────────┘    │
│                                                               │
│  Alimentation: 24V DC                                         │
└───────────────────────────────────────────────────────────────┘
```

---

## 1. Connexion USB Raspberry Pi ↔ Creality V4.2.2

| Raspberry Pi 4 | Câble | Creality V4.2.2 |
|----------------|-------|-----------------|
| Port USB-A     | Micro-USB ↔ USB-A | Port USB (micro-USB) |

- Longueur de câble recommandée: **< 1 mètre** (données haute vitesse)
- Standard USB 2.0 suffit (communication série 250000 baud)

---

## 2. Thermostat NTC 100K sur broche PA0

### Schéma de connexion:

```
          3.3V
           │
          [4.7K Ω]  ← Résistance pull-up
           │
           ├──────────────── PA0 (ADC0 Creality V4.2.2)
           │
        [NTC 100K]  ← Sonde de température
           │
          GND
```

### Câblage:

| Broche Creality V4.2.2 | Signal |
|------------------------|--------|
| PA0 (ADC0) | Signal thermostat (0-3.3V) |
| 3.3V | Tension pull-up |
| GND | Masse commune |

### Paramètres:
- **Type de sonde**: NTC 100K beta 3950
- **Résistance pull-up**: 4.7K Ohm
- **Tension**: 3.3V
- **Plage de mesure**: 0°C à 100°C

> **Note**: Le connecteur thermostat sur la Creality V4.2.2 est le connecteur
> "TH0" (extruder thermistor). Il est préconfiguré pour cette résistance pull-up.

---

## 3. Ventilateur 24V avec contrôle via PC6

### Schéma de connexion avec diode de roue libre:

```
                          24V DC
                           │
                           │
                    ┌──────┴──────┐
                    │             │
                 [RELAY]      [Diode 1N4007]
                    │          (cathode vers +24V)
                    └──────┬──────┘
                           │
                      [Ventilateur 24V]
                           │
                          GND

Contrôle relay:
PC6 (PWM) ──[470Ω]──[Base NPN]──GND
                          │
                       [Collecteur]── Bobine relay
                                           │
                                          GND
```

### Composants nécessaires:

| Composant | Valeur | Rôle |
|-----------|--------|------|
| Transistor NPN | 2N2222 ou BC547 | Commutation relay |
| Résistance base | 470 Ω (ou 1K) | Limitation courant base |
| Diode roue libre | 1N4007 | Protection contre surtension relay |
| Relay | 5V ou 3.3V, contact 24V | Commutation alimentation ventilateur |
| Condensateur de bypass | 100nF | Filtrage bruit CEM |

### Alternative simplifiée (ventilateur 5V):
Si le ventilateur supporte 5V/3.3V, connexion directe possible:
```
PC6 ──── + ventilateur (5V max, 0.5A max)
GND ──── - ventilateur
```

---

## 4. Lasers sur GPIO Raspberry Pi 4

### GPIO pins utilisés:

| GPIO | Fonction | Broche physique |
|------|----------|-----------------|
| GPIO17 | Laser gauche | Pin 11 |
| GPIO27 | Laser droit | Pin 13 |

### Schéma de connexion (avec module relay ou MOSFET):

```
GPIO17 ──[330Ω]──[LED relay/MOSFET]──GND
                        │
               Contrôle alimentation laser
```

### Alimentation des lasers:
- Consulter les spécifications du module laser utilisé
- Utiliser un relay ou MOSFET approprié selon la puissance
- **Ne jamais connecter directement un laser puissant sur un GPIO**

---

## 5. Moteurs pas-à-pas (connexion sur Creality V4.2.2)

Les connecteurs moteurs sont standards sur la Creality V4.2.2:

| Connecteur | Axe | Mouvement |
|------------|-----|-----------|
| XM | X | Translation avant/arrière |
| YM | Y | Rotation plateau 360° |
| ZM | Z | Montée/descente |

---

## 6. Endstops (fin de course)

| Connecteur | Axe | Position zéro |
|------------|-----|---------------|
| X-STOP | X | Position initiale translation |
| Y-STOP | Y | Référence rotation (0° = 1 tour complet) |
| Z-STOP | Z | Position basse (alignement Lidar + caméra) |

> **Type d'endstop**: Micro-switch NO (Normally Open) ou capteur Hall
> La configuration utilise `^` (pull-up activé) sur les broches endstop.

---

## 7. Alimentation générale

```
┌─────────────────────────────────────────┐
│  Alimentation 24V DC (20A minimum)       │
├─────────────────────────────────────────┤
│  ┌─────────────┐   ┌──────────────────┐ │
│  │ Creality    │   │  Convertisseur   │ │
│  │ V4.2.2 24V  │   │  DC-DC 24V→5V   │ │
│  │ (moteurs,   │   │  (5A) pour Pi4   │ │
│  │  ventilateur│   │  + USB           │ │
│  │  lasers)    │   └──────────────────┘ │
│  └─────────────┘                        │
└─────────────────────────────────────────┘
```

### Consommation estimée:

| Composant | Tension | Courant max |
|-----------|---------|-------------|
| Creality V4.2.2 | 24V | 5A |
| Raspberry Pi 4 | 5V (USB-C) | 3A |
| Lasers (x2) | Selon modèle | 1A |
| Ventilateur | 24V | 0.5A |
| **Total** | - | ~10A @ 24V |

---

## Notes de sécurité

⚠️ **Toujours éteindre l'alimentation avant de modifier le câblage**

⚠️ **Ne pas dépasser 3.3V sur les entrées GPIO du Raspberry Pi 4**

⚠️ **Utiliser des câbles de section appropriée pour 24V (min 0.75mm²)**

⚠️ **Installer un fusible de protection 15A sur l'alimentation 24V**

⚠️ **Les lasers de classe > 1 nécessitent des protections oculaires**
