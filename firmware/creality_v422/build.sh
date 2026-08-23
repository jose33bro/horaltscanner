#!/bin/bash
# build.sh - Script de compilation du firmware STM32
# Usage: ./build.sh [clean|flash|verify]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   STM32F103 Firmware Builder           ║${NC}"
echo -e "${BLUE}║   Creality V4.2.2 - Horaltscanner      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Vérifier les outils
echo -e "${BLUE}[1/5]${NC} Vérification des outils..."

if ! command -v arm-none-eabi-gcc &> /dev/null; then
    echo -e "${RED}✗ arm-none-eabi-gcc non trouvé${NC}"
    echo "  Installation:"
    echo "    Ubuntu: sudo apt-get install -y arm-none-eabi-gcc"
    echo "    Mac:    brew install arm-none-eabi-gcc"
    exit 1
fi

if ! command -v make &> /dev/null; then
    echo -e "${RED}✗ make non trouvé${NC}"
    exit 1
fi

echo -e "${GREEN}✓ arm-none-eabi-gcc$(NC) $(arm-none-eabi-gcc --version | head -1)"
echo -e "${GREEN}✓ make$(NC)"

# Vérifier le linker script
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

echo -e "${GREEN}✓ stm32f103_flash.ld${NC}"
echo -e "${GREEN}✓ src/main.c${NC}"

# Traiter les arguments
if [ "$1" = "clean" ]; then
    echo ""
    echo -e "${YELLOW}Nettoyage...${NC}"
    make clean
    exit 0
fi

if [ "$1" = "verify" ]; then
    echo ""
    echo -e "${BLUE}[3/5]${NC} Vérification de la connexion ST-LINK..."
    if ! command -v st-info &> /dev/null; then
        echo -e "${RED}✗ st-info non trouvé (stlink-tools)${NC}"
        exit 1
    fi
    st-info --probe
    exit 0
fi

# Compilation
echo ""
echo -e "${BLUE}[3/5]${NC} Compilation du firmware..."
make clean > /dev/null 2>&1
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

ELF_SIZE=$(stat -f%z "$FW_ELF" 2>/dev/null || stat -c%s "$FW_ELF" 2>/dev/null || echo "0")
echo -e "  Taille:       ${BLUE}$ELF_SIZE bytes${NC}"

make size

# Flashage
if [ "$1" = "flash" ]; then
    echo ""
    echo -e "${BLUE}[5/5]${NC} Flashage sur la Creality..."
    
    if ! command -v st-flash &> /dev/null; then
        echo -e "${RED}✗ st-flash non trouvé (stlink-tools)${NC}"
        echo "  Installation:"
        echo "    Ubuntu: sudo apt-get install -y stlink-tools"
        echo "    Mac:    brew install stlink"
        exit 1
    fi
    
    echo -e "${YELLOW}Connectez le ST-LINK V2 à la Creality V4.2.2...${NC}"
    echo -e "${YELLOW}Appuyez sur ENTRÉE pour commencer${NC}"
    read -p ""
    
    if ! st-flash write "$FW_HEX" 0x08000000; then
        echo -e "${RED}✗ Flashage échoué${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ Flashage réussi!${NC}"
    echo ""
    echo "Prochaines étapes:"
    echo "  1. Débrancher le ST-LINK"
    echo "  2. Rebrancher l'alimentation de la Creality"
    echo "  3. Brancher le câble USB au Raspberry Pi"
    echo "  4. Vérifier la connexion: lsusb | grep 1a86"
    echo ""
else
    echo ""
    echo -e "${GREEN}Compilation terminée!${NC}"
    echo ""
    echo "Pour flasher la Creality:"
    echo -e "  ${BLUE}./build.sh flash${NC}"
    echo ""
    echo "Pour vérifier ST-LINK:"
    echo -e "  ${BLUE}./build.sh verify${NC}"
    echo ""
    echo "Pour nettoyer:"
    echo -e "  ${BLUE}./build.sh clean${NC}"
    echo ""
fi
