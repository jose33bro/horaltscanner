#!/bin/bash
# flash.sh - Flashage du firmware STM32 sur Creality V4.2.2
# Usage: ./flash.sh <firmware.hex>

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Flashage Creality V4.2.2             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Vérifier les arguments
if [ $# -lt 1 ]; then
    FW_FILE="build/firmware.hex"
else
    FW_FILE="$1"
fi

if [ ! -f "$FW_FILE" ]; then
    echo -e "${RED}✗ Fichier non trouvé: $FW_FILE${NC}"
    echo "Usage: ./flash.sh <firmware.hex>"
    exit 1
fi

echo -e "${BLUE}[1/4]${NC} Vérification des outils..."

if ! command -v st-flash &> /dev/null; then
    echo -e "${RED}✗ st-flash non trouvé${NC}"
    echo "Installation:"
    echo "  Ubuntu: sudo apt-get install -y stlink-tools"
    echo "  Mac:    brew install stlink"
    exit 1
fi

echo -e "${GREEN}✓ st-flash disponible$(st-flash --version 2>/dev/null || echo "")"

# Détection du ST-LINK
echo ""
echo -e "${BLUE}[2/4]${NC} Recherche du ST-LINK V2..."

if ! command -v st-info &> /dev/null; then
    echo -e "${YELLOW}⚠ st-info non trouvé, continuant...${NC}"
else
    if ! st-info --probe 2>/dev/null | grep -q "STM32"; then
        echo -e "${YELLOW}⚠ Aucun ST-LINK détecté${NC}"
        echo "   Connectez le ST-LINK V2 à la Creality V4.2.2 (connecteur SWD)"
        echo -e "${YELLOW}   Appuyez sur ENTRÉE pour continuer...${NC}"
        read -p ""
    else
        echo -e "${GREEN}✓ STM32 détecté${NC}"
    fi
fi

# Affichage des informations
echo ""
echo -e "${BLUE}[3/4]{{NC} Préparation du flashage..."
echo -e "  Fichier:  ${BLUE}$FW_FILE${NC}"
echo -e "  Adresse:  ${BLUE}0x08000000${NC} (Flash STM32F103)"
echo -e "  Appareil: ${BLUE}Creality V4.2.2${NC}"

FW_SIZE=$(stat -f%z "$FW_FILE" 2>/dev/null || stat -c%s "$FW_FILE" 2>/dev/null || echo "0")
echo -e "  Taille:   ${BLUE}$FW_SIZE bytes${NC}"

# Confirmation
echo ""
echo -e "${YELLOW}ATTENTION: Le processus de flashage va redémarrer la Creality${NC}"
echo -e "${YELLOW}Assurez-vous que le ST-LINK V2 est bien connecté!${NC}"
echo ""
read -p "Continuer? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Annulé$(NC)"
    exit 0
fi

# Flashage
echo ""
echo -e "${BLUE}[4/4]${NC} Flashage en cours..."
echo -e "${YELLOW}Ne débranchez RIEN pendant le processus!${NC}"
echo ""

if st-flash write "$FW_FILE" 0x08000000; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   ✓ Flashage réussi!                  ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo "Prochaines étapes:"
    echo "  1. Débrancher le ST-LINK V2"
    echo "  2. Rebrancher l'alimentation de la Creality"
    echo "  3. Brancher le câble USB au Raspberry Pi"
    echo "  4. Vérifier: lsusb | grep 1a86"
    echo ""
else
    echo ""
    echo -e "${RED}✗ Erreur lors du flashage${NC}"
    echo "Solutions:"
    echo "  - Vérifiez que le ST-LINK V2 est connecté"
    echo "  - Vérifiez les câbles SWD (SWCLK, SWDIO, GND)"
    echo "  - Essayez de redémarrer le ST-LINK"
    exit 1
fi
