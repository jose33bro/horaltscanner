#!/bin/bash
# setup_pi_complete.sh - Setup COMPLET sur Raspberry Pi
# Installation outils + compilation + flashage + test
# Usage: bash setup_pi_complete.sh

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  SETUP COMPLET HORALTSCANNER - RASPBERRY PI              ${NC}"
echo -e "${BLUE}  Compilation + Flashage + Test Creality V4.2.2          ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

cd ~/horaltscanner/firmware/creality_v422

# Étape 1: Installation ST-LINK
echo -e "${BLUE}ÉTAPE 1: Installation ST-LINK${NC}"
echo ""
if command -v st-flash &> /dev/null; then
    echo -e "${GREEN}✓ st-flash déjà installé${NC}
    st-flash --version
else
    echo "Installation depuis GitHub..."
    bash install_stlink_pi.sh
fi

echo ""
echo -e "${BLUE}ÉTAPE 2: Compilation${NC}"
echo ""
./compile_pi.sh

echo ""
echo -e "${BLUE}ÉTAPE 3: Vérification ST-LINK${NC}"
echo ""
./compile_pi.sh verify

echo ""
echo -e "${BLUE}ÉTAPE 4: Flashage${NC}"
echo ""
read -p "Prêt pour le flashage? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    ./compile_pi.sh flash
else
    echo "Flashage ignoré"
fi

echo ""
echo -e "${BLUE}ÉTAPE 5: Test${NC}"
echo ""
read -p "Tester la Creality? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    bash test_creality.sh
else
    echo "Test ignoré"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  SETUP TERMINÉ! 🎉                                      ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
