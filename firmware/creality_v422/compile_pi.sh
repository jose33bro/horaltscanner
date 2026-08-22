#!/bin/bash
# compile_pi.sh - Compilation + Flashage Creality V4.2.2 sur Raspberry Pi
# Usage: ./compile_pi.sh [flash|verify]

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  STM32F103 Firmware Builder - Raspberry Pi               ${NC}"
echo -e "${BLUE}  Creality V4.2.2 - Horaltscanner                        ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Vérifier les outils
echo -e "${BLUE}[1/5]${NC} Vérification des outils..."

if ! command -v arm-none-eabi-gcc &> /dev/null; then
    echo -e "${RED}✗ arm-none-eabi-gcc non trouvé${NC}"
    exit 1
fi

echo -e "${GREEN}✓ arm-none-eabi-gcc$(NC) $(arm-none-eabi-gcc --version | head -1 | awk '{print $(NF-1)}')"

if ! command -v make &> /dev/null; then
    echo -e "${RED}✗ make non trouvé${NC}"
    exit 1
fi

echo -e "${GREEN}✓ make$(NC)"

# Vérifier les fichiers
echo ""
echo -e "${BLUE}[2/5]${NC} Vérification des fichiers source..."

if [ ! -f "stm32f103_flash.ld" ]; then
    echo -e "${RED}✗ Linker script manquant: stm32f103_flash.ld${NC}"
    exit 1
fi

if [ ! -f "src/main.c" ]; then
    echo -e "${RED}✗ Code source manquant: src/main.c${NC}"
    exit 1
fi

if [ ! -f "Makefile" ]; then
    echo -e "${RED}✗ Makefile manquant${NC}"
    exit 1
fi

echo -e "${GREEN}✓ stm32f103_flash.ld${NC}"
echo -e "${GREEN}✓ src/main.c${NC}"
echo -e "${GREEN}✓ Makefile${NC}"

# Traiter les arguments
if [ "$1" = "verify" ]; then
    echo ""
    echo -e "${BLUE}[3/5]${NC} Vérification ST-LINK..."
    if ! command -v st-info &> /dev/null; then
        echo -e "${RED}✗ st-info non trouvé${NC}"
        echo "Installation: bash install_stlink_pi.sh"
        exit 1
    fi
    st-info --probe
    exit 0
fi

if [ "$1" = "clean" ]; then
    echo ""
    echo -e "${YELLOW}Nettoyage...${NC}"
    rm -rf build/
    echo -e "${GREEN}✓ Nettoyé${NC}"
    exit 0
fi

# Compilation
echo ""
echo -e "${BLUE}[3/5]${NC} Compilation du firmware..."
make clean > /dev/null 2>&1 || true
make all

FW_ELF="build/firmware.elf"
FW_HEX="build/firmware.hex"
FW_BIN="build/firmware.bin"

if [ ! -f "$FW_ELF" ]; then
    echo -e "${RED}✗ Compilation échouée${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Compilation réussie${NC}"

# Informations
echo ""
echo -e "${BLUE}[4/5]${NC} Informations du firmware..."
echo -e "  Fichier ELF:  ${BLUE}$FW_ELF${NC}"
echo -e "  Fichier HEX:  ${BLUE}$FW_HEX${NC}"
echo -e "  Fichier BIN:  ${BLUE}$FW_BIN${NC}"

ELF_SIZE=$(stat -c%s "$FW_ELF" 2>/dev/null || echo "0")
echo -e "  Taille:       ${BLUE}$ELF_SIZE bytes${NC}"

make size

# Flashage
if [ "$1" = "flash" ]; then
    echo ""
    echo -e "${BLUE}[5/5]${NC} Flashage sur la Creality..."
    
    if ! command -v st-flash &> /dev/null; then
        echo -e "${RED}✗ st-flash non trouvé${NC}"
        echo "Installation: bash install_stlink_pi.sh"
        exit 1
    fi
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  VÉRIFICATION AVANT FLASHAGE${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo "Checklist:"
    echo "  ☐ ST-LINK V2 connecté au Pi (USB)"
    echo "  ☐ ST-LINK SWD connecté à Creality (SWCLK, SWDIO, GND)"
    echo "  ☐ Creality alimentée en 5V/24V"
    echo "  ☐ Aucun autre périphérique USB ne flashe"
    echo ""
    
    echo -e "${YELLOW}Vérification ST-LINK...${NC}"
    if ! st-info --probe 2>&1 | grep -q "STM32"; then
        echo -e "${RED}✗ ST-LINK non détecté ou Creality non connectée${NC}"
        echo ""
        echo "Solutions:"
        echo "  1. Vérifier la connexion USB ST-LINK"
        echo "  2. Vérifier les câbles SWD (SWCLK, SWDIO, GND)"
        echo "  3. Essayer: st-info --probe"
        exit 1
    fi
    
    echo -e "${GREEN}✓ ST-LINK détecté et Creality trouvée${NC}"
    echo ""
    
    read -p "Continuer avec le flashage? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Annulé${NC}"
        exit 0
    fi
    
    echo -e "${YELLOW}NE DÉCONNECTEZ RIEN PENDANT LE FLASHAGE!${NC}"
    echo ""
    
    if st-flash write "$FW_HEX" 0x08000000; then
        echo ""
        echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  ✓✓✓ FLASHAGE RÉUSSI! 🎉                             ${NC}"
        echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
        echo ""
        echo "Prochaines étapes:"
        echo "  1. Débrancher ST-LINK V2"
        echo "  2. Rebrancher l'alimentation Creality (elle va redémarrer)"
        echo "  3. Attendre 2 secondes"
        echo "  4. Brancher le câble USB Creality au Raspberry Pi"
        echo "  5. Vérifier: lsusb | grep 1a86"
        echo "  6. Tester: python3 ../../../software/tests/test_usb_driver.py"
        echo ""
    else
        echo ""
        echo -e "${RED}✗ Erreur lors du flashage${NC}"
        echo ""
        echo "Dépannage:"
        echo "  st-info --probe"
        exit 1
    fi
else
    echo ""
    echo -e "${GREEN}Compilation terminée!${NC}"
    echo ""
    echo "Pour flasher:"
    echo -e "  ${BLUE}./compile_pi.sh flash${NC}"
    echo ""
    echo "Pour vérifier ST-LINK:"
    echo -e "  ${BLUE}./compile_pi.sh verify${NC}"
    echo ""
    echo "Pour nettoyer:"
    echo -e "  ${BLUE}./compile_pi.sh clean${NC}"
    echo ""
fi
