# Guide d'installation et configuration Klipper - Horaltscanner

## Table des matières

1. [Prérequis](#1-prérequis)
2. [Installation de Klipper sur Raspberry Pi 4](#2-installation-de-klipper-sur-raspberry-pi-4)
3. [Flash du firmware MCU Creality V4.2.2](#3-flash-du-firmware-mcu-creality-v422)
4. [Configuration du fichier printer.cfg](#4-configuration-du-fichier-printercfg)
5. [Configuration du thermostat et ventilateur](#5-configuration-du-thermostat-et-ventilateur)
6. [Configuration de la carte SD virtuelle](#6-configuration-de-la-carte-sd-virtuelle)
7. [Câblage et connexions](#7-câblage-et-connexions)
8. [Premier démarrage et vérifications](#8-premier-démarrage-et-vérifications)
9. [Utilisation des macros de scan](#9-utilisation-des-macros-de-scan)
10. [Dépannage](#10-dépannage)

---

## 1. Prérequis

### Matériel nécessaire:

| Composant | Spécification |
|-----------|---------------|
| Raspberry Pi 4 | 4 Go RAM, microSD 32 Go min |
| Creality V4.2.2 | STM32F103RET6, alimentation 24V |
| Câble USB | Micro-USB vers USB-A, < 1m |
| Sonde température | NTC 100K beta 3950 |
| Ventilateur | 24V DC, 40x40mm |
| Transistor NPN | 2N2222 ou TIP120 |
| Diode de roue libre | 1N4007 |
| Résistance | 4.7K Ω (pull-up NTC), 470Ω (base transistor) |

### Logiciels requis:

- **Raspbian Bullseye 64-bit** (image officielle Raspberry Pi)
- **Klipper** (firmware + host)
- **Moonraker** (API Klipper)
- **Mainsail** (interface web)

---

## 2. Installation de Klipper sur Raspberry Pi 4

### 2.1 Préparer la carte microSD

1. Télécharger **Raspberry Pi Imager**: https://rptl.io/imager
2. Sélectionner: Raspberry Pi OS (64-bit) Lite
3. Configurer avant flash (⚙ icône):
   - Hostname: `horaltscanner`
   - SSH activé
   - Wifi (si nécessaire)
   - Utilisateur: `pi`

### 2.2 Lancer le script d'installation

Se connecter en SSH sur le Raspberry Pi:

```bash
ssh pi@horaltscanner.local
```

Cloner le dépôt et lancer l'installation:

```bash
git clone https://github.com/jose33bro/horaltscanner.git ~/horaltscanner
cd ~/horaltscanner
chmod +x installation/klipper_install.sh
./installation/klipper_install.sh
```

Le script installe automatiquement:
- Klipper (firmware host)
- Moonraker (API)
- Mainsail (interface web)
- Nginx (serveur web)
- Toutes les dépendances

### 2.3 Vérifier l'installation

```bash
sudo systemctl status klipper
sudo systemctl status moonraker
sudo systemctl status nginx
```

Tous les services doivent afficher `active (running)`.

---

## 3. Flash du firmware MCU Creality V4.2.2

**Voir le guide détaillé**: [`installation/mcu_flashing.md`](../installation/mcu_flashing.md)

### Résumé rapide:

```bash
cd ~/klipper
make menuconfig
# Paramètres: STM32F103, 28KiB bootloader, USB PA11/PA12
make clean && make -j4

# Mettre la carte en mode DFU (jumper BOOT0)
sudo dfu-util -a 0 -s 0x08007000:leave -D out/klipper.bin
```

---

## 4. Configuration du fichier printer.cfg

Le fichier principal de configuration est `klipper_config/printer.cfg`.
Il inclut automatiquement les autres fichiers de configuration:

```ini
[include creality_v422_usb.cfg]   # MCU et moteurs
[include temperature_fan.cfg]      # Thermostat et ventilateur
[include scanner_macros.cfg]       # Macros de scan 3D
```

### 4.1 Identifier le port USB de la carte Creality

```bash
ls /dev/serial/by-id/
# Output exemple:
# usb-Klipper_stm32f103xe_42FFD7055648323731761943-if00
```

### 4.2 Mettre à jour le port série

Éditer `klipper_config/creality_v422_usb.cfg`:

```ini
[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32f103xe_VOTRE_ID-if00
```

### 4.3 Configuration des axes du scanner

| Axe | Mouvement | Endstop | Position zéro |
|-----|-----------|---------|---------------|
| **X** | Translation avant/arrière | PA5 | Position initiale |
| **Y** | Rotation plateau 360° | PA6 | Référence 0° (après 1 tour) |
| **Z** | Montée/descente | PA7 | Lidar + caméra alignés |

---

## 5. Configuration du thermostat et ventilateur

### 5.1 Connexion de la sonde NTC 100K

Voir schéma KiCad: `hardware/thermostat_circuit.sch`

**Connexion sur Creality V4.2.2**:
- Brancher la sonde NTC 100K sur le connecteur **"TH0"** (thermistance extrudeur)
- La résistance pull-up 4.7K et la tension 3.3V sont déjà intégrées sur la carte

### 5.2 Configuration dans temperature_fan.cfg

```ini
[temperature_sensor board_temp]
sensor_type: NTC 100K beta 3950
sensor_pin: PA0
pullup_resistor: 4700
```

### 5.3 Câblage du ventilateur 24V

Voir guide détaillé: `hardware/fan_wiring.md`

Le ventilateur est contrôlé automatiquement:
- **Température < 50°C**: Ventilateur arrêté
- **Température ≥ 50°C**: Ventilateur démarre (vitesse proportionnelle)
- **Température > 70°C**: Alerte dans la console

---

## 6. Configuration de la carte SD virtuelle

Klipper utilise un **SD virtuel** (répertoire sur le Raspberry Pi) pour stocker
les fichiers G-code et les séquences de scan.

### 6.1 Configuration dans printer.cfg

```ini
[virtual_sdcard]
path: /home/pi/gcode_files
on_error_gcode: CANCEL_PRINT
```

### 6.2 Créer le répertoire

```bash
mkdir -p /home/pi/gcode_files
```

### 6.3 Accès via Mainsail

L'interface Mainsail permet de:
- **Uploader** des fichiers G-code/séquences de scan
- **Lancer** des séquences depuis l'interface web
- **Monitorer** l'état du scan en temps réel

---

## 7. Câblage et connexions

**Voir le schéma complet**: [`installation/wiring_diagram.md`](../installation/wiring_diagram.md)

### Résumé des connexions:

| Source | Destination | Câble |
|--------|-------------|-------|
| Raspberry Pi USB-A | Creality V4.2.2 micro-USB | USB 2.0 < 1m |
| Raspberry Pi GPIO17 | Module laser gauche | Câble signal 3.3V |
| Raspberry Pi GPIO27 | Module laser droit | Câble signal 3.3V |
| Raspberry Pi DSI | Caméra Pi V3 Noir | Câble DSI officiel |
| Creality PA0 (TH0) | Sonde NTC 100K | Câble 2 fils |
| Creality PC6 (FAN) | Transistor → Ventilateur 24V | Câble signal + puissance |

---

## 8. Premier démarrage et vérifications

### 8.1 Démarrer les services

```bash
sudo systemctl start klipper moonraker
```

### 8.2 Accéder à Mainsail

Ouvrir un navigateur: `http://horaltscanner.local/` ou `http://[IP_DU_PI]/`

### 8.3 Vérifications initiales dans la console Klipper

```gcode
; Vérifier les températures
CHECK_TEMP

; Vérifier le statut du scanner
SCANNER_STATUS

; Tester le homing (ATTENTION: s'assurer que les axes sont libres)
SCANNER_HOME
```

### 8.4 Test des lasers

```gcode
; Activer les lasers
LASERS_ON

; Vérifier visuellement
; ...

; Désactiver les lasers
LASERS_OFF
```

---

## 9. Utilisation des macros de scan

Les macros de scan sont définies dans `klipper_config/scanner_macros.cfg`.

### Macros disponibles:

| Macro | Description |
|-------|-------------|
| `SCANNER_HOME` | Home tous les axes (X, Y, Z) |
| `SCAN_FULL` | Scan 3D complet (toutes couches X + rotation 360° Y) |
| `SCAN_ROTATE_360` | Un seul plan de scan (rotation 360° à position X courante) |
| `SCAN_QUICK` | Scan rapide (résolution 5° par pas) |
| `CALIBRATE_SCANNER` | Procédure de calibration |
| `LASERS_ON` | Activer les deux lasers |
| `LASERS_OFF` | Désactiver les lasers |
| `SCANNER_STATUS` | Afficher l'état du scanner |
| `SCANNER_EMERGENCY_STOP` | Arrêt d'urgence |
| `CHECK_TEMP` | Afficher les températures système |
| `FAN_ON` | Forcer le ventilateur à pleine vitesse |
| `FAN_OFF` | Arrêter le ventilateur |

### Exemple de séquence de scan:

```gcode
; 1. Initialiser
SCANNER_HOME

; 2. Ajuster la hauteur Z pour l'objet
G1 Z50 F600

; 3. Lancer un scan rapide pour prévisualisation
SCAN_QUICK

; 4. Lancer un scan complet (haute résolution)
SCAN_FULL
```

---

## 10. Dépannage

### Klipper ne démarre pas

```bash
# Voir les logs
journalctl -u klipper -n 50
cat ~/printer_data/logs/klippy.log | tail -50
```

### Creality V4.2.2 non détectée

```bash
# Vérifier les périphériques USB
lsusb
ls /dev/serial/by-id/
dmesg | grep -i tty
```

### Erreur "Unable to connect" au MCU

- Vérifier que le firmware Klipper est bien flashé sur la Creality
- Vérifier le port série dans `creality_v422_usb.cfg`
- Vérifier les permissions: `sudo usermod -aG dialout pi`

### Température non lue (NTC 100K)

- Vérifier la connexion sur le connecteur TH0 de la Creality
- Vérifier le type de thermistance dans la config: `NTC 100K beta 3950`
- Mesurer la résistance de la sonde à température ambiante (doit être ~100K à 25°C)

### Ventilateur ne démarre pas

- Vérifier les connexions du transistor et de la diode de roue libre
- Tester manuellement: `FAN_ON` dans la console Klipper
- Vérifier la tension 24V sur l'alimentation

### Lasers ne s'allument pas

- Vérifier la configuration du MCU secondaire (Raspberry Pi GPIO):
  ```ini
  [mcu rpi]
  serial: /tmp/klipper_host_mcu
  ```
- Installer le service klipper-mcu sur le Raspberry Pi:
  ```bash
  cd ~/klipper
  sudo cp scripts/klipper-mcu.service /etc/systemd/system/
  sudo systemctl enable klipper-mcu
  sudo systemctl start klipper-mcu
  ```

### Moonraker API non accessible

```bash
sudo systemctl status moonraker
cat ~/printer_data/logs/moonraker.log | tail -20
```

---

## Ressources

- [Documentation Klipper officielle](https://www.klipper3d.org/)
- [Moonraker API docs](https://moonraker.readthedocs.io/)
- [Mainsail documentation](https://docs.mainsail.xyz/)
- [Creality V4.2.2 schematic](https://github.com/Klipper3d/klipper/tree/master/config)
- [STM32F103 datasheet](https://www.st.com/en/microcontrollers-microprocessors/stm32f103.html)
