#!/bin/bash
# HoralScanner Installation & Update Guide
# Complete reference for all installation methods

cat > INSTALL_GUIDE.md <<'EOF'
# 🚀 HoralScanner Installation Guide

Complete guide for installing or updating HoralScanner on Raspberry Pi 4.

---

## 📋 Table of Contents

1. [Quick Overview](#quick-overview)
2. [Installation Methods](#installation-methods)
3. [Method A: Fresh Pi OS Install](#method-a-fresh-pi-os-install)
4. [Method B: Update Existing Pi with Klipper](#method-b-update-existing-pi-with-klipper)
5. [Method C: Create Pre-configured OS Image](#method-c-create-pre-configured-os-image)
6. [Verification & Testing](#verification--testing)
7. [Troubleshooting](#troubleshooting)

---

## Quick Overview

| Method | Use Case | Time | Difficulty |
|--------|----------|------|------------|
| **A** | Fresh Pi, no OS yet | 30-45 min | ⭐ Easy |
| **B** | Has Klipper, want to replace | 20-30 min | ⭐⭐ Medium |
| **C** | Create reusable OS image | 60-90 min | ⭐⭐⭐ Hard |

---

## Installation Methods

### Method A: Fresh Pi OS Install ✅ RECOMMENDED
**For:** Brand new Raspberry Pi 4 with fresh Raspberry Pi OS

**Steps:**
1. Flash Raspberry Pi OS Bookworm 64-bit to SD card
2. Boot Pi and SSH in
3. Run `setup_pi.sh --full`
4. Reboot
5. Access dashboard on port 5000

**Time:** 30-45 minutes
**File:** `setup_pi.sh`

---

### Method B: Update Existing Pi (Remove Klipper)
**For:** Pi running Klipper that you want to replace

**Steps:**
1. SSH into your Pi
2. Run `update_pi_clean.sh`
3. Confirm removal of Klipper
4. Reboot
5. Access dashboard on port 5000

**Time:** 20-30 minutes
**File:** `update_pi_clean.sh`

---

### Method C: Create Pre-configured OS Image
**For:** Building a reusable image to flash multiple Pis or as backup

**Steps:**
1. On Linux host with 20GB free space
2. Run `build_clean_os_image.sh`
3. Wait for build (60-90 minutes)
4. Flash compressed image to SD cards
5. Boot and use immediately

**Time:** 60-90 minutes
**File:** `build_clean_os_image.sh`

---

## ✅ Method A: Fresh Pi OS Install

### Prerequisites
- Raspberry Pi 4 (4GB+ RAM recommended)
- SD card (16GB+ recommended)
- USB power adapter
- Computer with SD card reader
- Network access (WiFi or Ethernet)

### Step-by-Step

#### 1. Flash Raspberry Pi OS

```bash
# Download Raspberry Pi Imager
# https://www.raspberrypi.com/software/

# Or use command line (on Linux/Mac):
wget https://downloads.raspberrypi.org/raspios_arm64/images/raspios_arm64-2024-03-12/2024-03-12-raspios-bookworm-arm64-lite.img.xz
xzcat 2024-03-12-raspios-bookworm-arm64-lite.img.xz | dd of=/dev/sdX bs=4M status=progress sync
```

#### 2. Boot Pi and Connect

```bash
# Insert SD card, power on, wait for boot
# SSH from another computer:
ssh pi@raspberrypi.local
# Password: raspberry (default)
```

#### 3. Run Installation Script

```bash
# Option A: From GitHub (recommended)
sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/setup_pi.sh | bash"

# Option B: From local repo
git clone https://github.com/jose33bro/horaltscanner.git
cd horaltscanner
sudo bash setup_pi.sh --full
```

**What it does:**
- Updates system (apt-get update/upgrade)
- Installs all dependencies
- Configures GPIO, I2C, SPI, UART
- Clones HoralScanner repo
- Creates Python venv
- Installs Python packages (~10 minutes)
- Installs systemd service
- Starts service

#### 4. Reboot

```bash
sudo reboot
```

#### 5. Verify & Access

```bash
# Check service status
sudo systemctl status horalscanner

# View logs
sudo journalctl -u horalscanner -f

# Access dashboard
# Open browser: http://raspberrypi.local:5000
# or: http://<your-pi-ip>:5000
```

---

## ✅ Method B: Update Existing Pi (Remove Klipper)

### Prerequisites
- Raspberry Pi 4 with Klipper installed
- SSH access
- ~500MB free disk space
- ~15 minutes

### Step-by-Step

#### 1. SSH into Pi

```bash
ssh pi@raspberrypi.local
```

#### 2. Run Clean Update Script

```bash
# Option A: From GitHub
sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/update_pi_clean.sh | bash"

# Option B: From local repo
cd ~/horaltscanner
sudo bash ../update_pi_clean.sh
```

**What it does:**
- Stops Klipper/Moonraker services
- Backs up old config to `/home/pi/backups_old_system_*`
- Removes Klipper, Moonraker, Mainsail, Nginx
- Updates Raspberry Pi OS
- Installs HoralScanner
- Installs systemd service
- Enables GPIO access

#### 3. Confirm Removal

```
⚠️  This will COMPLETELY remove Klipper and replace with HoralScanner
Continue? (yes/no): yes
```

#### 4. Automatic Reboot (or manual)

Script will ask to reboot. Confirm with `yes`.

#### 5. Verify Installation

```bash
# Check service
sudo systemctl status horalscanner

# View logs
sudo journalctl -u horalscanner -f

# Access dashboard
# http://<your-pi-ip>:5000
```

---

## ✅ Method C: Create Pre-configured OS Image

### Prerequisites
- Linux host with 20GB+ free disk space
- sudo/root access
- Tools: wget, xz-utils, losetup, parted, qemu-user-static

### Step-by-Step

#### 1. Prepare Linux Host

```bash
# Ensure you have enough space
df -h /

# Install required tools (if needed)
sudo apt-get install -y wget xz-utils util-linux parted qemu-user-static
```

#### 2. Clone Repository

```bash
git clone https://github.com/jose33bro/horaltscanner.git
cd horaltscanner
```

#### 3. Run Image Builder

```bash
# This takes 60-90 minutes!
sudo bash build_clean_os_image.sh
```

**What it does:**
- Downloads Raspberry Pi OS Bookworm 64-bit (500MB)
- Extracts base image
- Expands image (+2GB)
- Mounts filesystem
- Installs HoralScanner in chroot
- Unmounts filesystem
- Compresses image (xz)
- Creates documentation

#### 4. Output

Image will be in `horaltscanner-os-build/` directory:
```
horaltscanner-os-build/
├── horaltscanner-bookworm-lite.img.xz (compressed ~1.5GB)
├── horaltscanner-bookworm-lite.img    (uncompressed ~10GB)
└── README_IMAGE.txt                   (flashing instructions)
```

#### 5. Flash to Multiple SD Cards

```bash
# Get the compressed image
IMAGE="horaltscanner-os-build/horaltscanner-bookworm-lite.img.xz"

# Find SD card device
lsblk

# Flash (replace sdX with actual device, e.g., sdb)
sudo bash -c "xzcat $IMAGE | dd of=/dev/sdX bs=4M status=progress sync"

# Eject
sudo eject /dev/sdX
```

#### 6. Boot Pi with Image

- Insert SD card into Pi 4
- Power on
- Wait for boot (~30 seconds)
- SSH in: `ssh pi@raspberrypi.local`
- Dashboard ready at: `http://raspberrypi.local:5000`

---

## Verification & Testing

### 1. Check Service Status

```bash
sudo systemctl status horalscanner
```

Expected output:
```
● horalscanner.service - HoralScanner 3D Scanner API
     Loaded: loaded (/etc/systemd/system/horalscanner.service; enabled; vendor preset: enabled)
     Active: active (running) since ...
```

### 2. View Live Logs

```bash
sudo journalctl -u horalscanner -f
```

### 3. Test API Endpoints

```bash
# Health check
curl http://localhost:5000/api/status

# Expected response:
# {"success": true, "status": {"api": "ok", "gpio_driver": true, "stm32_driver": false, "version": "1.0.0"}}

# Get laser status
curl http://localhost:5000/api/laser/status

# Get temperature
curl http://localhost:5000/api/temperature/board
```

### 4. Access Web Dashboard

Open browser:
```
http://<your-pi-ip>:5000
```

Should show:
- ✅ **Status:** API Connected
- ✅ **GPIO Driver:** Connected
- ⚠️ **STM32 Driver:** Disconnected (until board is powered)

### 5. Test Controls

From dashboard:
- [ ] Toggle laser (if enabled)
- [ ] Change LED color
- [ ] Move motors (after wiring)
- [ ] Adjust fans
- [ ] Read temperature

---

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u horalscanner -n 50

# Common issues:
# - GPIO permissions: sudo usermod -a -G gpio pi
# - Port in use: sudo lsof -i :5000
# - Python error: Check pip install output
```

### GPIO Driver Not Available

```bash
# Add user to gpio group
sudo usermod -a -G gpio pi
sudo usermod -a -G dialout pi

# Reboot
sudo reboot

# Re-check
sudo systemctl status horalscanner
```

### Can't Connect to STM32 Board

```bash
# Check USB connection
lsusb
dmesg | grep -i stm32

# Check serial ports
ls /dev/tty*

# Test connection manually
python3 -c "import serial; s=serial.Serial('/dev/ttyUSB0', 115200); print('OK')"
```

### Port 5000 Already in Use

```bash
# Find process
sudo lsof -i :5000

# Kill it
sudo kill -9 <PID>

# Or change port in horalscanner_api.py
# (not recommended)
```

### Python Import Errors

```bash
# Activate venv and reinstall
source /home/pi/horaltscanner_env/bin/activate
pip install --upgrade -r /home/pi/horaltscanner/requirements.txt
```

### Slow Performance

```bash
# Check available RAM
free -h

# Check disk space
df -h

# Check CPU temperature
vcgencmd measure_temp

# HoralScanner performance:
# - Should not use >30% CPU
# - Memory usage: ~100-200MB
# - API response <100ms
```

---

## Post-Installation Setup

### 1. Change Default Password

```bash
passwd
```

### 2. Configure Hostname

```bash
sudo raspi-config
# System Options → Hostname
```

### 3. Enable WiFi (Optional)

```bash
sudo raspi-config
# System Options → Wireless LAN
# Select country and network
```

### 4. Wire Hardware

Follow: `hardware/wiring_diagram.md`

### 5. Set Up SSH Keys (Recommended)

```bash
# On your computer
ssh-copy-id pi@raspberrypi.local

# On Pi (disable password auth)
sudo nano /etc/ssh/sshd_config
# Change: PasswordAuthentication no
sudo systemctl restart ssh
```

### 6. Enable Firewall (Recommended)

```bash
sudo apt-get install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp  # SSH
sudo ufw allow 5000/tcp # HoralScanner
sudo ufw enable
```

---

## Updating HoralScanner

### Option 1: Auto-Update (Recommended)

```bash
bash /home/pi/horaltscanner/software/scripts/update.sh
```

### Option 2: Manual Update

```bash
cd /home/pi/horaltscanner
git pull origin main
source /home/pi/horaltscanner_env/bin/activate
pip install -r requirements.txt --upgrade
deactivate
sudo systemctl restart horalscanner
```

---

## Uninstalling HoralScanner

```bash
# Stop service
sudo systemctl stop horalscanner
sudo systemctl disable horalscanner

# Remove service file
sudo rm /etc/systemd/system/horalscanner.service

# Remove code (optional)
rm -rf /home/pi/horaltscanner
rm -rf /home/pi/horaltscanner_env

# Reload systemd
sudo systemctl daemon-reload
```

---

## Script Comparison

| Script | Purpose | Use When | Time |
|--------|---------|----------|------|
| `setup_pi.sh` | Fresh install | Starting from clean Raspberry Pi OS | 30-45 min |
| `update_pi_clean.sh` | Remove Klipper | Migrating from Klipper | 20-30 min |
| `build_clean_os_image.sh` | Create reusable image | Building for multiple Pis | 60-90 min |
| `software/scripts/update.sh` | Update code only | Already running, want latest version | 5-10 min |

---

## Support

- **Issues:** https://github.com/jose33bro/horaltscanner/issues
- **Quick Start:** [QUICK_START.md](QUICK_START.md)
- **API Docs:** [USAGE.md](USAGE.md)
- **Deployment:** [DEPLOYMENT.md](DEPLOYMENT.md)

---

## Checklist

- [ ] Pi 4 with Raspberry Pi OS installed
- [ ] SSH access working
- [ ] Installation script completed
- [ ] Service running (`systemctl status horalscanner`)
- [ ] Web dashboard accessible on port 5000
- [ ] GPIO driver connected
- [ ] Hardware wired correctly
- [ ] Changed default password
- [ ] Tested at least one API endpoint
- [ ] Firewall configured (recommended)

---

**Ready to scan!** 🎉

Get started: Choose your method above and follow the steps.

EOF

cat INSTALL_GUIDE.md
