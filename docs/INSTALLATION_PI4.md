# Installation Horaltscanner sur Raspberry Pi 4

Guide complet d'installation du scanner 3D USB sur un Raspberry Pi 4 avec Creality V4.2.2.

## Table des matières

1. [Prérequis matériel](#prérequis-matériel)
2. [Préparation SD Card](#préparation-sd-card)
3. [Configuration SSH](#configuration-ssh)
4. [Installation système](#installation-système)
5. [Installation Python](#installation-python)
6. [Clonage du dépôt](#clonage-du-dépôt)
7. [Configuration matériel](#configuration-matériel)
8. [Test](#test)
9. [Démarrage automatique](#démarrage-automatique)

---

## Prérequis matériel

### Composants
- **Raspberry Pi 4** (4Go RAM minimum)
- **SD Card** 32Go ou plus (Classe 10)
- **Alimentation USB-C** 5V/3A minimum
- **Câble réseau Ethernet** ou WiFi
- **Adaptateur USB** pour la Creality V4.2.2
- **Caméra Raspberry Pi V3 NoIR** (connecteur DSI)
- **Webcam USB Logitech C270**
- **LiDAR TF-Luna** (USB)
- **Dissipateur thermique** pour le Pi

### Branchements
```
Raspberry Pi 4
├── USB (moteurs STM32) → Creality V4.2.2
├── USB → Logitech C270
├── USB → LiDAR TF-Luna
├── DSI → Caméra Pi V3 NoIR
├── GPIO27 → Laser gauche
├── GPIO22 → Laser droit
├── GPIO18 → LED R (PWM)
├── GPIO13 → LED G (PWM)
├── GPIO19 → LED B (PWM)
└── GPIO23 → Ventilateur Pi
```

---

## Préparation SD Card

### 1. Télécharger Raspberry Pi OS

```bash
# Sur votre ordinateur (Linux/Mac/Windows)
# Télécharger Raspberry Pi OS Lite 64-bit depuis:
# https://www.raspberrypi.com/software/operating-systems/

# OU utiliser Raspberry Pi Imager:
# https://www.raspberrypi.com/software/
```

### 2. Flasher la SD Card

**Avec Raspberry Pi Imager (GUI):**
- Ouvrir Raspberry Pi Imager
- Sélectionner "Raspberry Pi OS (64-bit)"
- Sélectionner votre SD Card
- Cliquer "Écrire"

**Avec dd (CLI):**
```bash
# Identifier la SD Card
lsblk

# Flasher (remplacer sdX par votre device)
sudo dd if=2024-XX-XX-raspios-bookworm-arm64-lite.img of=/dev/sdX bs=4M status=progress
sync
```

### 3. Configuration initiale (avant démarrage)

Après le flashage, la SD Card contient une partition boot. Vous pouvez pré-configurer:

**Activer SSH (ajouter fichier vide):**
```bash
# Sur la partition boot:
touch /boot/ssh
```

**Pré-configurer WiFi (optionnel):**
```bash
# Créer /boot/wpa_supplicant.conf
cat > /boot/wpa_supplicant.conf << 'EOF'
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=FR

network={
    ssid="votre_wifi"
    psk="votre_mot_de_passe"
    key_mgmt=WPA-PSK
}
EOF
```

---

## Configuration SSH

### 1. Premier démarrage et connexion

```bash
# Brancher la SD Card, allumer le Pi
# Attendre ~2 minutes pour le démarrage

# Trouver l'adresse IP du Pi
arp-scan --local
# OU
nmap -sn 192.168.1.0/24
# OU (si sur réseau local)
ping raspberrypi.local

# Se connecter via SSH
ssh pi@raspberrypi.local
# OU
ssh pi@<IP_ADDRESS>

# Mot de passe par défaut: raspberry
```

### 2. Changer le mot de passe

```bash
# Sur le Pi
passwd
# Entrer le nouveau mot de passe
```

### 3. Configurer une clé SSH (recommandé)

**Sur votre ordinateur:**
```bash
# Générer une paire de clés (si vous n'en avez pas)
ssh-keygen -t ed25519 -C "horaltscanner"
# Sauvegarder dans ~/.ssh/id_horaltscanner

# Copier la clé publique vers le Pi
ssh-copy-id -i ~/.ssh/id_horaltscanner.pub pi@raspberrypi.local
# OU manuellement:
cat ~/.ssh/id_horaltscanner.pub | ssh pi@raspberrypi.local 'cat >> .ssh/authorized_keys'
```

**Vérifier la connexion sans mot de passe:**
```bash
ssh -i ~/.ssh/id_horaltscanner pi@raspberrypi.local
```

**Configurer ~/.ssh/config (optionnel):**
```bash
cat >> ~/.ssh/config << 'EOF'
Host horaltscanner
    HostName raspberrypi.local
    User pi
    IdentityFile ~/.ssh/id_horaltscanner
    StrictHostKeyChecking no
EOF

# Maintenant vous pouvez faire:
ssh horaltscanner
```

### 4. Désactiver l'authentification par mot de passe (sécurité)

```bash
# Sur le Pi
sudo nano /etc/ssh/sshd_config
# Modifier/ajouter ces lignes:
# PasswordAuthentication no
# PubkeyAuthentication yes

sudo systemctl restart ssh
```

---

## Installation système

```bash
# Sur le Pi, via SSH
ssh pi@raspberrypi.local

# Mettre à jour le système
sudo apt update
sudo apt upgrade -y

# Installer les dépendances système
sudo apt install -y \
    python3-pip \
    python3-dev \
    git \
    cmake \
    build-essential \
    libopencv-dev \
    python3-opencv \
    libatlas-base-dev \
    libjasper-dev \
    libtiff5 \
    libjasper1 \
    libharfbuzz0b \
    libwebp6 \
    libtiff5 \
    libopenjp2-7 \
    libopenjp2-7-dev \
    libharfbuzz0b \
    libwebp6 \
    libjasper1 \
    libtiff5 \
    libatlas-base-dev \
    libharfbuzz0b \
    libwebp6 \
    libopenjp2-7

# Activer les interfaces I2C, SPI, Camera (optionnel)
sudo raspi-config
# Interface Options → Camera → Enable
# Interface Options → I2C → Enable
# Interface Options → Serial → Enable (pour LiDAR)
```

---

## Installation Python

```bash
# Créer un virtualenv
cd ~
python3 -m venv horaltscanner_env
source horaltscanner_env/bin/activate

# Mettre à pip à jour
pip install --upgrade pip setuptools wheel

# Installer les dépendances Python
pip install pyserial>=3.5
pip install gpiozero>=1.6.0
pip install opencv-python>=4.5
pip install numpy>=1.21.0
pip install pillow>=8.3.0
pip install pytest>=7.0.0
pip install pytest-cov>=3.0.0

# Optionnel: picamera2 (caméra Pi)
pip install picamera2
```

---

## Clonage du dépôt

```bash
# Se placer dans le répertoire
cd ~

# Configurer Git (si nécessaire)
git config --global user.name "Votre Nom"
git config --global user.email "votre.email@example.com"

# Cloner le dépôt
git clone https://github.com/jose33bro/horaltscanner.git
cd horaltscanner

# Sélectionner la branche USB
git checkout copilot/create-usb-firmware

# Vérifier les fichiers
ls -la firmware/raspberry_pi/
ls -la software/tests/
```

---

## Configuration matériel

### 1. Identifier les ports USB

```bash
# Lister tous les périphériques USB
lsusb

# Lister les ports série
ls -la /dev/ttyUSB*
ls -la /dev/ttyACM*

# Obtenir les identifiants persistants
ls -la /dev/serial/by-id/

# Exemple:
# /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0  → Creality (moteurs)
# /dev/ttyUSB1                                       → LiDAR TF-Luna
```

### 2. Mettre à jour config.py

```bash
# Éditer la configuration
nano ~/horaltscanner/firmware/raspberry_pi/config.py

# Vérifier/modifier:
# USB_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
# GPIO pins (27, 22, 18, 13, 19, 23)
```

### 3. Tester les connexions

```bash
# Vérifier USB moteurs
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.usb_driver import USBDriver

driver = USBDriver()
if driver.connect():
    print("✓ Moteurs connectés")
    driver.ping()
    driver.disconnect()
else:
    print("✗ Erreur connexion moteurs")
EOF

# Vérifier GPIO
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.gpio_laser_control import GPIOLaserControl

gpio = GPIOLaserControl(use_board=False)  # Mode simulation
print("✓ GPIO initialisé (simulation)")
EOF

# Vérifier caméras
v4l2-ctl --list-devices
```

---

## Test

### 1. Tests unitaires

```bash
# Activer virtualenv
source ~/horaltscanner_env/bin/activate
cd ~/horaltscanner

# Exécuter tous les tests
python -m pytest software/tests/ -v

# Tests spécifiques
python -m pytest software/tests/test_usb_driver.py -v
python -m pytest software/tests/test_motor_control.py -v
```

### 2. Test d'initialisation scanner

```bash
# Mode simulation (sans matériel)
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.scanner_app import ScannerApp

app = ScannerApp(use_gpio=False)  # Simulation
if app.initialize():
    print("✓ Scanner initialisé")
    app.laser_test(100)
    app.led_test()
    app.shutdown()
else:
    print("✗ Erreur initialisation")
EOF
```

### 3. Test complet avec matériel

```bash
# Vérifier que tout est connecté!
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.scanner_app_full import ScannerAppFull

with ScannerAppFull(use_gpio=True) as scanner:
    print(f"Moteurs hômés: {scanner.motors.is_homed()}")
    print(f"Caméras: {scanner.cameras is not None}")
    print(f"LiDAR: {scanner.lidar is not None}")
EOF
```

---

## Démarrage automatique

### 1. Créer un script systemd

```bash
# Créer le service
sudo nano /etc/systemd/system/horaltscanner.service
```

```ini
[Unit]
Description=Horaltscanner 3D Scanner
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/horaltscanner
Environment="PATH=/home/pi/horaltscanner_env/bin"
ExecStart=/home/pi/horaltscanner_env/bin/python3 -m firmware.raspberry_pi.scanner_app_full
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

### 2. Activer le service

```bash
# Recharger les services
sudo systemctl daemon-reload

# Activer au démarrage
sudo systemctl enable horaltscanner.service

# Démarrer le service
sudo systemctl start horaltscanner.service

# Vérifier le statut
sudo systemctl status horaltscanner.service

# Voir les logs
journalctl -u horaltscanner.service -f
```

---

## Dépannage

### Problème: Impossible de se connecter en SSH

```bash
# Vérifier que SSH est activé
sudo systemctl status ssh

# Vérifier l'adresse IP
ip addr show eth0
# OU
ifconfig

# Trouver le Pi sur le réseau
arp-scan --local | grep -i raspberry
```

### Problème: Import module échoue

```bash
# Vérifier le PYTHONPATH
export PYTHONPATH=/home/pi/horaltscanner/firmware:$PYTHONPATH
python3 -c "from raspberry_pi import USBDriver"
```

### Problème: Ports USB ne sont pas trouvés

```bash
# Vérifier les permissions
sudo usermod -a -G dialout pi
sudo usermod -a -G gpio pi

# Redémarrer
sudo reboot

# Vérifier après redémarrage
ls -la /dev/ttyUSB*
ls -la /dev/serial/by-id/
```

### Problème: GPIO ne fonctionne pas

```bash
# Vérifier que l'utilisateur est dans le groupe gpio
groups pi

# Si absent, ajouter:
sudo usermod -a -G gpio pi

# Redémarrer
sudo reboot
```

---

## Accès au dépôt depuis le Pi

### Avec SSH key

```bash
# Sur le Pi, générer une clé
ssh-keygen -t ed25519 -C "pi@horaltscanner"

# Afficher la clé publique
cat ~/.ssh/id_ed25519.pub

# Ajouter cette clé dans GitHub:
# Settings → SSH and GPG keys → New SSH key

# Tester la connexion
ssh -T git@github.com

# Cloner avec SSH
git clone git@github.com:jose33bro/horaltscanner.git
```

---

## Utilisation

### Exemple simple

```bash
# Activer virtualenv
source ~/horaltscanner_env/bin/activate

# Créer un script de scan
cat > ~/scan.py << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.scanner_app_full import ScannerAppFull

with ScannerAppFull() as scanner:
    # Scan simple
    scanner.run_full_scan(
        num_positions=10,
        z_heights=[50, 100],
        lidar_samples=20
    )
EOF

# Exécuter
python3 ~/scan.py
```

### Outputs

Les résultats du scan sont sauvegardés dans:
```
/tmp/horaltscanner_scan_YYYYMMDD_HHMMSS/
├── images/
│   ├── pi_v3/
│   │   ├── position_00000_pi.png
│   │   └── ...
│   └── usb_logitech/
│       ├── position_00000_usb.png
│       └── ...
├── lidar_measurements.csv
└── scan_metadata.json
```

---

## Support

Pour l'aide:
- Consulter les logs: `journalctl -u horaltscanner.service -f`
- Vérifier les tests: `python -m pytest software/tests/ -v`
- GitHub Issues: https://github.com/jose33bro/horaltscanner/issues

