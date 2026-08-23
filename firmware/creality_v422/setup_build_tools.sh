#!/bin/bash
# setup_build_tools.sh - Installation des outils de compilation ARM
# Usage: ./setup_build_tools.sh

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Installation Outils ARM/STM32        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Détecter l'OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" =~ ^(ubuntu|debian)$ ]]; then
            DISTRO="debian"
        elif [[ "$ID" == "fedora" ]]; then
            DISTRO="fedora"
        fi
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="mac"
else
    OS="unknown"
fi

echo -e "${BLUE}OS détecté: $OS${NC}"
echo ""

echo -e "${BLUE}[1/3]${NC} Installation arm-none-eabi-gcc..."

case "$OS" in
    linux)
        case "$DISTRO" in
            debian)
                echo "Debian/Ubuntu détecté"
                echo -e "${YELLOW}Exécution de: sudo apt-get update && sudo apt-get install -y ...${NC}"
                sudo apt-get update
                sudo apt-get install -y \
                    build-essential \
                    arm-none-eabi-gcc \
                    arm-none-eabi-binutils \
                    arm-none-eabi-newlib \
                    stlink-tools \
                    openocd
                ;;
            fedora)
                echo "Fedora détecté"
                sudo dnf install -y \
                    arm-none-eabi-gcc-cs \
                    arm-none-eabi-binutils \
                    arm-none-eabi-newlib \
                    stlink \
                    openocd
                ;;
            *)
                echo -e "${YELLOW}Distro non reconnue, installation manuelle requise${NC}"
                echo "Références:"
                echo "  https://developer.arm.com/tools-and-software/open-source-toolchains/gnu-toolchain/gnu-rm/downloads"
                exit 1
                ;;
        esac
        ;;
    mac)
        echo "macOS détecté"
        if ! command -v brew &> /dev/null; then
            echo -e "${RED}Homebrew requis. Installez depuis: https://brew.sh${NC}"
            exit 1
        fi
        brew install \
            arm-none-eabi-gcc \
            stlink \
            openocd
        ;;
    *)
        echo -e "${RED}OS non supporté${NC}"
        exit 1
        ;;
esac

echo -e "${GREEN}✓ Installation réussie${NC}"

# Vérification
echo ""
echo -e "${BLUE}[2/3]${NC} Vérification des outils..."

echo -n "  arm-none-eabi-gcc: "
if command -v arm-none-eabi-gcc &> /dev/null; then
    echo -e "${GREEN}✓$(NC) $(arm-none-eabi-gcc --version | head -1 | cut -d' ' -f3-)"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "  arm-none-eabi-ar: "
if command -v arm-none-eabi-ar &> /dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "  st-flash: "
if command -v st-flash &> /dev/null; then
    echo -e "${GREEN}✓${NC} $(st-flash --version 2>/dev/null | head -1 || echo "")"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "  st-info: "
if command -v st-info &> /dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo -n "  openocd: "
if command -v openocd &> /dev/null; then
    echo -e "${GREEN}✓${NC} $(openocd --version 2>/dev/null | head -1 || echo "")"
else
    echo -e "${YELLOW}⚠${NC} (optionnel)"
fi

echo ""
echo -e "${BLUE}[3/3]${NC} Finalisation..."
echo ""
echo -e "${GREEN}✓ Outils installés avec succès!${NC}"
echo ""
echo "Prochaines étapes:"
echo "  1. cd firmware/creality_v422"
echo "  2. ./build.sh"
echo "  3. ./build.sh flash (avec ST-LINK V2 connecté)"
echo ""
