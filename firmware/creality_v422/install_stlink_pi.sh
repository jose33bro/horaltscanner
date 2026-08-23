#!/bin/bash
# install_stlink_pi.sh - Installation de STLINK-TOOLS depuis GitHub sur Raspberry Pi
# Usage: bash install_stlink_pi.sh

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Installation STLINK-TOOLS sur Raspberry Pi             ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Vérifier si déjà installé
if command -v st-flash &> /dev/null; then
    echo -e "${GREEN}✓ st-flash déjà installé$(NC)"
    st-flash --version
    exit 0
fi

echo -e "${BLUE}[1/5]${NC} Installation dépendances..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    build-essential \
    cmake \
    libusb-1.0-0-dev \
    pkg-config \
    git \
    2>/dev/null

echo -e "${GREEN}✓ Dépendances installées${NC}"

echo -e "${BLUE}[2/5]${NC} Clonage du dépôt STLINK..."
cd /tmp
rm -rf stlink 2>/dev/null || true
git clone -q --depth 1 https://github.com/stlink-org/stlink.git
cd stlink

echo -e "${GREEN}✓ Dépôt cloné${NC}"

echo -e "${BLUE}[3/5]${NC} Configuration CMAKE..."
mkdir -p build
cd build
cmake -DCMAKE_BUILD_TYPE=Release .. > /dev/null 2>&1

echo -e "${GREEN}✓ Configuration terminée${NC}"

echo -e "${BLUE}[4/5]${NC} Compilation (cela peut prendre 2-3 minutes)...
make -j4 > /dev/null 2>&1

echo -e "${GREEN}✓ Compilation réussie${NC}"

echo -e "${BLUE}[5/5]${NC} Installation...
sudo make install > /dev/null 2>&1
sudo ldconfig

echo -e "${GREEN}✓ Installation réussie${NC}"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ STLINK-TOOLS Installé avec Succès!                  ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Vérification
echo -e "${BLUE}Vérification...${NC}"
st-flash --version
st-info --version

echo ""
echo "Prochaines étapes:"
echo "  1. Connecter ST-LINK V2 au Pi"
echo "  2. Connecter ST-LINK SWD → Creality V4.2.2"
echo "  3. Lancer: cd ~/horaltscanner/firmware/creality_v422 && ./compile_pi.sh"
echo ""
