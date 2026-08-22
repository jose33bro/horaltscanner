# Flash du firmware Klipper sur Creality V4.2.2 (STM32F103RET6)

## Vue d'ensemble

La Creality V4.2.2 utilise un microcontrôleur **STM32F103RET6**. Pour utiliser Klipper,
il faut compiler et flasher le firmware Klipper sur cette carte.

---

## Prérequis

- Raspberry Pi 4 avec Klipper installé (voir `klipper_install.sh`)
- Câble USB (micro-USB) entre Raspberry Pi et Creality V4.2.2
- Tournevis pour accéder aux jumpers BOOT0

---

## Étape 1 : Compiler le firmware Klipper pour STM32F103

Se connecter en SSH sur le Raspberry Pi et exécuter:

```bash
cd ~/klipper
make menuconfig
```

### Paramètres de configuration menuconfig:

| Paramètre | Valeur |
|-----------|--------|
| Micro-controller Architecture | **STM32** |
| Processor model | **STM32F103** |
| Bootloader offset | **28KiB bootloader** |
| Communication interface | **USB (on PA11/PA12)** |
| USB ids | Laisser par défaut |

Quitter et sauvegarder, puis compiler:

```bash
make clean
make -j4
```

Le fichier firmware sera généré à: `~/klipper/out/klipper.bin`

---

## Étape 2 : Méthode de flash (DFU via USB)

### 2a. Mettre la carte en mode DFU (Bootloader)

1. **Éteindre** la carte Creality V4.2.2
2. Localiser le jumper **BOOT0** sur la carte (marqué `BOOT`)
3. Placer le jumper en position **1-2** (ou court-circuiter les broches BOOT0 vers 3.3V)
4. **Connecter le câble USB** entre la carte et le Raspberry Pi
5. **Allumer** la carte (ou appuyer sur RESET)

Vérifier que la carte est détectée en mode DFU:

```bash
lsusb
# Doit afficher quelque chose comme:
# Bus 001 Device 003: ID 0483:df11 STMicroelectronics STM Device in DFU Mode
```

### 2b. Flasher avec dfu-util

```bash
cd ~/klipper

# Flasher le firmware
sudo dfu-util -a 0 -s 0x08007000:leave -D out/klipper.bin
```

Si `dfu-util` donne une erreur, essayer:

```bash
sudo dfu-util -a 0 -s 0x08007000 -D out/klipper.bin
sudo dfu-util -E 0.5 -a 0 -s 0x08007000:leave -D out/klipper.bin
```

### 2c. Remettre en mode normal

1. **Éteindre** la carte
2. **Remettre** le jumper BOOT0 en position normale (0-1 ou aucun jumper)
3. **Rallumer** la carte

---

## Étape 3 : Méthode alternative - Flash via carte SD

Si le DFU ne fonctionne pas, il est possible de flasher via carte SD:

```bash
# Renommer le fichier firmware
cp ~/klipper/out/klipper.bin /tmp/firmware.bin

# Copier sur une carte SD FAT32
# Sur Linux:
sudo mount /dev/sdX1 /mnt
sudo cp /tmp/firmware.bin /mnt/
sudo umount /mnt
```

1. Insérer la carte SD dans le slot de la Creality V4.2.2
2. Allumer la carte → le flash démarre automatiquement
3. Attendre 30 secondes (LED clignote pendant le flash)

---

## Étape 4 : Vérifier l'installation

Après le flash:

```bash
# Vérifier que la carte est visible en USB
ls /dev/serial/by-id/
# Doit afficher quelque chose comme:
# usb-Klipper_stm32f103xe_XXXXXXXXXXXXXXXXXXXXXXXXXX-if00

# Tester la connexion
screen /dev/ttyACM0 250000
# Ctrl+A puis K pour quitter
```

---

## Étape 5 : Configurer le port série dans Klipper

Éditer `/home/pi/printer_data/config/creality_v422_usb.cfg`:

```ini
[mcu]
serial: /dev/serial/by-id/usb-Klipper_stm32f103xe_XXXXXXXXXXXXXXXXXXXXXXXXXX-if00
```

Remplacer `XXXXXXXXXXXXXXXXXXXXXXXXXX` par l'identifiant réel de ta carte.

---

## Dépannage

### La carte n'est pas détectée en mode DFU

```bash
# Vérifier les périphériques USB
lsusb -t
dmesg | tail -20
```

- Vérifier que le jumper BOOT0 est bien en position haute
- Essayer un autre câble USB
- Vérifier que `dfu-util` est installé: `sudo apt-get install dfu-util`

### Erreur "Can't init USB" avec dfu-util

```bash
# Donner les permissions USB
sudo chmod 666 /dev/bus/usb/001/003
# Ou ajouter une règle udev
```

### Klipper affiche "Unable to connect"

```bash
# Vérifier le port série
ls -la /dev/serial/by-id/
# Vérifier les permissions
ls -la /dev/ttyACM0
sudo usermod -aG dialout pi
# Se déconnecter et reconnecter
```

---

## Références

- [Documentation Klipper STM32](https://www.klipper3d.org/Bootloaders.html#stm32f103-micro-controllers-blue-pill-devices)
- [Creality V4.2.2 pinout](https://github.com/Klipper3d/klipper/blob/master/config/printer-creality-ender3-v2-2021.cfg)
