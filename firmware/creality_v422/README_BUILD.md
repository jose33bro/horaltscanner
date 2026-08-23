# Compilation du Firmware STM32F103 - Creality V4.2.2

## 📋 Table des matières

1. [Installation des outils](#installation-des-outils)
2. [Compilation](#compilation)
3. [Flashage](#flashage)
4. [Dépannage](#dépannage)

---

## 🛠️ Installation des outils

### Automatique (recommandé)

```bash
cd firmware/creality_v422
bash setup_build_tools.sh
```

### Manuel

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    arm-none-eabi-gcc \
    arm-none-eabi-binutils \
    arm-none-eabi-newlib \
    stlink-tools \
    openocd
```

**macOS:**
```bash
brew install arm-none-eabi-gcc stlink openocd
```

**Windows:**
- Télécharger ARM GNU Toolchain: https://developer.arm.com/tools-and-software/open-source-toolchains/gnu-toolchain/gnu-rm/downloads
- Télécharger STLink Tools: https://github.com/stlink-org/stlink/releases

---

## 🔨 Compilation

### Avec le script bash

```bash
cd firmware/creality_v422
./build.sh
```

**Résultat:**
```
build/firmware.elf   - Exécutable ELF
build/firmware.hex   - Format hexadécimal (pour ST-LINK)
build/firmware.bin   - Format binaire
```

### Avec make directement

```bash
cd firmware/creality_v422
make clean
make all
make size        # Voir la taille
```

### Avec ARM GCC en ligne de commande

```bash
cd firmware/creality_v422

# Compilation
arm-none-eabi-gcc \
  -mcpu=cortex-m3 -mthumb -msoft-float \
  -Wall -Wextra -O2 -g3 \
  -ffunction-sections -fdata-sections \
  -c src/main.c -o build/main.o

# Linking
arm-none-eabi-gcc \
  -mcpu=cortex-m3 -mthumb -msoft-float \
  -Wl,--gc-sections -nostartfiles \
  -T stm32f103_flash.ld \
  build/main.o -o build/firmware.elf

# Conversion hexadécimal
arm-none-eabi-objcopy -O ihex build/firmware.elf build/firmware.hex
```

---

## 📤 Flashage

### Matériel requis

- **ST-LINK V2** (ou compatible)
- Connecteur SWD sur la Creality V4.2.2
- Câbles de connexion (SWCLK, SWDIO, GND)

### Branchement ST-LINK → Creality

| ST-LINK V2 | Creality V4.2.2 | Signal |
|-----------|-----------------|--------|
| SWCLK     | SWCLK          | Clock  |
| SWDIO     | SWDIO          | Data   |
| GND       | GND            | Ground |
| VCC (opt) | VCC            | Power  |

### Flashage avec le script

```bash
cd firmware/creality_v422

# Compiler et flasher en une commande
./build.sh flash

# OU juste flasher un fichier existant
./flash.sh build/firmware.hex
```

### Flashage avec st-flash directement

```bash
# Vérifier la détection
st-info --probe

# Flasher
st-flash write build/firmware.hex 0x08000000
```

### Flashage avec OpenOCD

```bash
openocd -f interface/stlink-v2.cfg \
        -f target/stm32f1x.cfg \
        -c "program build/firmware.elf verify reset exit 0x08000000"
```

---

## ✅ Vérification

### Sur l'ordinateur

```bash
# Vérifier la compilation
file build/firmware.elf
arm-none-eabi-size build/firmware.elf

# Vérifier le flashage
st-info --probe
st-flash read /tmp/flash_dump.bin 0x08000000 4096
hexdump -C /tmp/flash_dump.bin | head
```

### Sur le Raspberry Pi

```bash
ssh horaltscanner

# Lister les périphériques USB
lsusb | grep 1a86

# Vérifier le port série
ls -la /dev/serial/by-id/

# Tester la connexion
python3 << 'EOF'
import sys
sys.path.insert(0, '/home/pi/horaltscanner/firmware')
from raspberry_pi.usb_driver import USBDriver

driver = USBDriver()
if driver.connect():
    print("✓ Firmware détecté!")
    driver.ping()
    driver.disconnect()
else:
    print("✗ Erreur connexion")
EOF
```

---

## 🐛 Dépannage

### Erreur: "arm-none-eabi-gcc: command not found"

```bash
# Réinstaller
sudo apt-get install -y arm-none-eabi-gcc

# OU ajouter au PATH
export PATH=$PATH:/opt/gcc-arm/bin
```

### Erreur: "st-flash: command not found"

```bash
# Installer stlink-tools
sudo apt-get install -y stlink-tools

# OU depuis GitHub
git clone https://github.com/stlink-org/stlink.git
cd stlink
cmake .
make
sudo make install
```

### Erreur: "STM32 not found" lors du flashage

**Solutions:**
1. Vérifier les câbles SWD
2. Vérifier l'alimentation de la Creality
3. Essayer avec `-u` (unlock):
   ```bash
   st-flash -u write build/firmware.hex 0x08000000
   ```
4. Réinitialiser le STM32:
   ```bash
   openocd -f interface/stlink-v2.cfg -f target/stm32f1x.cfg -c "init; reset halt; exit"
   ```

### Le firmware ne démarre pas après flashage

1. Vérifier que le linker script est correct
2. Vérifier l'adresse de flashage (devrait être 0x08000000)
3. Redémarrer manuellement la Creality
4. Essayer un firmware test (clignotement LED)

### USB CDC non reconnu après flashage

1. Installer les drivers CDC (Linux/Mac: automatique)
2. Vérifier: `lsusb | grep 1a86`
3. Ajouter l'utilisateur au groupe dialout:
   ```bash
   sudo usermod -a -G dialout $USER
   ```

---

## 📚 Ressources

- [ARM GNU Toolchain](https://developer.arm.com/tools-and-software/open-source-toolchains/gnu-toolchain/gnu-rm)
- [STM32F103 Reference](https://www.st.com/en/microcontrollers/stm32f103.html)
- [STLINK Tools](https://github.com/stlink-org/stlink)
- [OpenOCD](https://openocd.org/)

---

## 🎯 Flux de travail complet

```bash
# 1. Installation des outils (une seule fois)
cd firmware/creality_v422
bash setup_build_tools.sh

# 2. Compilation
./build.sh

# 3. Vérification de la taille
make size

# 4. Vérifier ST-LINK
make verify

# 5. Flashage (avec ST-LINK connecté)
./build.sh flash

# 6. Débrancher ST-LINK
# 7. Brancher USB au Raspberry Pi

# 8. Tester sur le Pi
ssh horaltscanner
python3 -c "from raspberry_pi.usb_driver import USBDriver; USBDriver().ping()"
```

---

**Status: Prêt pour production** ✅
