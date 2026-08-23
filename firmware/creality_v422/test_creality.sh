#!/bin/bash
# test_creality.sh - Test complet Creality après flashage
# Usage: ./test_creality.sh

set -e

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Test Creality V4.2.2 Après Flashage                     ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Test 1: Détection USB
echo -e "${BLUE}[1/4]${NC} Détection USB..."
echo ""
echo "Périphériques USB:"
lsusb | grep -E "1a86|Creality" || echo "  (aucun trouvé)"
echo ""

if lsusb | grep -q "1a86"; then
    echo -e "${GREEN}✓ Creality détectée${NC}"
else
    echo -e "${YELLOW}⚠ Creality non détectée (essayez de rebrancher l'USB)${NC}"
    echo ""
    echo "Solutions:"
    echo "  - Vérifier le câble USB"
    echo "  - Redémarrer la Creality"
    echo "  - Attendre 5 secondes et réessayer"
    exit 1
fi

echo ""

# Test 2: Port série
echo -e "${BLUE}[2/4]${NC} Détection port série..."
echo ""
echo "Ports série disponibles:"
ls -la /dev/serial/by-id/ 2>/dev/null | grep usb || ls -la /dev/ttyUSB* 2>/dev/null || echo "  (aucun trouvé)"
echo ""

if [ -e /dev/ttyUSB0 ] || ls /dev/serial/by-id/ | grep -q "usb-1a86"; then
    echo -e "${GREEN}✓ Port série détecté${NC}"
else
    echo -e "${YELLOW}⚠ Port série non détecté${NC}"
fi

echo ""

# Test 3: Imports Python
echo -e "${BLUE}[3/4]{{NC} Vérification imports Python..."
echo ""

cd ~/horaltscanner
source ~/horaltscanner_env/bin/activate

if python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.usb_driver import USBDriver
print("✓ USBDriver importé")
EOF
then
    echo -e "${GREEN}✓ Modules OK${NC}"
else
    echo -e "${RED}✗ Erreur imports${NC}"
    exit 1
fi

echo ""

# Test 4: Connexion Creality
echo -e "${BLUE}[4/4]${NC} Test connexion Creality..."
echo ""

python3 << 'EOF'
import sys
import time
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.usb_driver import USBDriver

driver = USBDriver()

print("Tentative connexion...")
if driver.connect():
    print("✓ Connecté!")
    print("")
    
    # Test PING
    print("Test PING...")
    try:
        response = driver.ping()
        print(f"✓ Réponse: {response}")
    except Exception as e:
        print(f"✗ Erreur PING: {e}")
    
    print("")
    
    # Test STATUS
    print("Test STATUS...")
    try:
        driver.send_command("ENDSTOP Y")
        print("✓ Endstop Y OK")
    except Exception as e:
        print(f"⚠ Endstop: {e}")
    
    driver.disconnect()
    print("")
    print("✓✓✓ Creality fonctionnelle!")
else:
    print("✗ Erreur connexion")
    print("")
    print("Solutions:")
    print("  - Vérifier USB: lsusb | grep 1a86")
    print("  - Redémarrer Creality")
    print("  - Vérifier le port: ls /dev/ttyUSB*")
EOF

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Test Terminé!                                           ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
