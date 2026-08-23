#!/bin/bash
# install_horaltscanner.sh - Script d'installation automatique
# À exécuter sur un Raspberry Pi 4 fraîchement flashé

set -e  # Arrêter en cas d'erreur

echo "========================================"
echo "Installation Horaltscanner"
echo "========================================"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonctions
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Vérifier root
if [ "$(id -u)" -eq 0 ]; then
    warning "N'exécutez PAS ce script en root"
    exit 1
fi

info "Mise à jour du système..."
sudo apt update
sudo apt upgrade -y

info "Installation des dépendances système..."
sudo apt install -y \
    python3-pip \
    python3-dev \
    git \
    cmake \
    build-essential \
    libopencv-dev \
    python3-opencv \
    libatlas-base-dev \
    libharfbuzz0b \
    libwebp6 \
    libjasper1 \
    libtiff5 \
    libopenjp2-7 \
    libopenjp2-7-dev

info "Activation des interfaces..."
sudo raspi-config nonint do_camera 0 2>/dev/null || warning "Camera interface config failed"
sudo raspi-config nonint do_i2c 0 2>/dev/null || warning "I2C config failed"
sudo raspi-config nonint do_serial_hw 0 2>/dev/null || warning "Serial config failed"

info "Création du virtualenv..."
cd ~
python3 -m venv horaltscanner_env
source horaltscanner_env/bin/activate

info "Installation des dépendances Python..."
pip install --upgrade pip setuptools wheel
pip install \
    pyserial>=3.5 \
    gpiozero>=1.6.0 \
    opencv-python>=4.5 \
    numpy>=1.21.0 \
    pillow>=8.3.0 \
    pytest>=7.0.0 \
    pytest-cov>=3.0.0

# Optionnel: picamera2
info "Installation de picamera2..."
pip install picamera2 || warning "picamera2 install failed (optionnel)"

info "Clonage du dépôt Horaltscanner..."
cd ~
git clone https://github.com/jose33bro/horaltscanner.git
cd horaltscanner
git checkout copilot/create-usb-firmware

info "Configuration des permissions GPIO..."
sudo usermod -a -G dialout $USER
sudo usermod -a -G gpio $USER
sudo usermod -a -G video $USER

info "Test de l'installation..."
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
try:
    from raspberry_pi.usb_driver import USBDriver
    from raspberry_pi.motor_control import MotorController
    from raspberry_pi.gpio_laser_control import GPIOLaserControl
    print("✓ Modules importés avec succès")
except Exception as e:
    print(f"✗ Erreur import: {e}")
    exit(1)
EOF

info "Installation des tests..."
python3 -m pytest software/tests/ --co -q

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Installation terminée!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Prochaines étapes:"
echo "1. Redémarrer: sudo reboot"
echo "2. Vérifier les connexions matériel"
echo "3. Mettre à jour config.py avec vos ports USB"
echo "4. Exécuter: python3 ~/horaltscanner/firmware/raspberry_pi/scanner_app.py"
echo ""
echo "Virtualenv:"
echo "source ~/horaltscanner_env/bin/activate"
echo ""
