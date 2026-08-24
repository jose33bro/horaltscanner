#!/bin/bash
# HoralScanner — Quick Install Guide Generator
# Creates a step-by-step installation instruction file

cat > QUICK_START.md <<'EOF'
# 🚀 HoralScanner — Quick Start Guide

**Goal:** Convert your Raspberry Pi 4 from Klipper/Marlin to HoralScanner 3D Scanner with custom STM32 USB firmware.

---

## 📋 Prerequisites

- **Hardware:**
  - Raspberry Pi 4 (4GB+ recommended)
  - Creality V4.2.2 board (STM32F103RET6)
  - USB cable (Micro-B, data-capable)
  - Stable power supply
  - SD card (16GB+)

- **Software:**
  - Raspberry Pi OS (Bookworm 64-bit Lite) or newer
  - SSH access to your Pi

- **Knowledge:**
  - Basic Linux/terminal commands
  - Ability to connect USB devices

---

## 🎯 Installation Paths

Choose **ONE** based on your situation:

### **Path A: Fresh Setup (Recommended)**
**For:** New Pi or willing to erase everything

```bash
# 1. Flash fresh Raspberry Pi OS to SD card
# Download: https://www.raspberrypi.com/software/

# 2. SSH into your Pi
ssh pi@raspberrypi.local

# 3. Run full installation
sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/setup_pi.sh | bash"

# 4. Reboot
sudo reboot

# 5. Access dashboard
# http://<your-pi-ip>:5000
```

**Time:** ~30-45 minutes (includes system updates and Python compilation)

---

### **Path B: Migrate from Klipper (Current Setup)**
**For:** Existing Klipper installation on your Pi

```bash
# 1. SSH into your Pi
ssh pi@raspberrypi.local

# 2. Run migration script
sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/remove_klipper_install_horaltscanner.sh | bash"

# 3. When prompted, prepare Creality board for firmware flashing
#    - Disconnect power
#    - Connect USB to Pi
#    - Press RESET, then hold BOOT button

# 4. Reboot
sudo reboot

# 5. Verify service is running
sudo systemctl status horalscanner
```

**Time:** ~45-60 minutes (compilation + firmware flashing)

---

### **Path C: Update Existing HoralScanner**
**For:** Already running HoralScanner, want latest code

```bash
# Run update script
bash /home/pi/horaltscanner/software/scripts/update.sh
```

**Time:** ~10 minutes

---

## 🔧 Manual Setup (If Scripts Fail)

### Step 1: System Update
```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    build-essential python3-dev \
    libopencv-dev python3-opencv \
    git curl
```

### Step 2: Clone Repository
```bash
git clone https://github.com/jose33bro/horaltscanner.git ~/horaltscanner
cd ~/horaltscanner
```

### Step 3: Python Environment
```bash
python3 -m venv ~/horaltscanner_env
source ~/horaltscanner_env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: systemd Service
```bash
sudo cp setup_pi.sh /tmp/setup_pi.sh
sudo bash /tmp/setup_pi.sh --install
```

### Step 5: Start Service
```bash
sudo systemctl start horalscanner
sudo systemctl status horalscanner
```

### Step 6: Access Dashboard
```
http://<your-pi-ip>:5000
```

---

## 🔌 Hardware Wiring

**Before powering on**, wire your components according to:

📄 `hardware/wiring_diagram.md` in the repo

**Key GPIO mappings (Raspberry Pi):**
- GPIO27: Laser Left
- GPIO22: Laser Right
- GPIO18/13/19: LED (R/G/B)
- GPIO23: Pi Fan PWM

**Creality V4.2.2 (STM32F103):**
- PC2/PB9/PC3: Stepper X (step/dir/enable)
- PB8/PB7/PC3: Stepper Y (step/dir/enable)
- PB6/PB5/PC3: Stepper Z (step/dir/enable)
- PA0: Creality Fan PWM
- PA8: Temperature Fan PWM
- PC5: Board Temperature Sensor

---

## 🧪 Verify Installation

### Check Service Status
```bash
sudo systemctl status horalscanner
```

### View Live Logs
```bash
sudo journalctl -u horalscanner -f
```

### Test API
```bash
# Health check
curl http://localhost:5000/api/status

# Get laser status
curl http://localhost:5000/api/laser/status

# Get motor status
curl http://localhost:5000/api/motor/status
```

### Web Dashboard
```
http://<your-pi-ip>:5000
```

You should see:
- ✅ **API:** Connected
- ✅ **GPIO Driver:** Connected
- ✅ **STM32 Driver:** Connected (when board is powered)
- 🌡️ **Temperature:** Real-time board temperature
- 🎛️ **Controls:** Lasers, LEDs, Motors, Fans

---

## 📋 API Quick Reference

### Lasers
```bash
# Turn left laser ON
curl -X POST http://localhost:5000/api/laser/left \
  -H "Content-Type: application/json" \
  -d '{"state": true}'

# Turn left laser OFF
curl -X POST http://localhost:5000/api/laser/left \
  -H "Content-Type: application/json" \
  -d '{"state": false}'
```

### LED Color
```bash
# Set LED to red
curl -X POST http://localhost:5000/api/led/color \
  -H "Content-Type: application/json" \
  -d '{"r": 255, "g": 0, "b": 0}'
```

### Motors
```bash
# Move X axis 10mm
curl -X POST http://localhost:5000/api/move/x \
  -H "Content-Type: application/json" \
  -d '{"mm": 10.0}'

# Home all axes
curl -X POST http://localhost:5000/api/home/all

# Get motor positions
curl http://localhost:5000/api/motor/status
```

### Fans
```bash
# Set Pi fan to 50%
curl -X POST http://localhost:5000/api/fan/pi \
  -H "Content-Type: application/json" \
  -d '{"percent": 50}'

# Set Creality fan to 75%
curl -X POST http://localhost:5000/api/fan/creality \
  -H "Content-Type: application/json" \
  -d '{"percent": 75}'
```

### Temperature
```bash
# Get board temperature
curl http://localhost:5000/api/temperature/board
```

Full API docs: 📖 `USAGE.md`

---

## 🛠️ Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u horalscanner -n 50

# If GPIO driver fails:
sudo usermod -a -G gpio pi
sudo reboot

# If STM32 driver fails:
# Check USB connection: 
lsusb
dmesg | grep -i stm32
```

### Port 5000 already in use
```bash
sudo lsof -i :5000
sudo kill -9 <PID>
```

### Can't connect to Creality board
```bash
# List serial devices
ls /dev/tty*

# Check USB connection
dmesg | tail -20

# Test connection manually
python3 -c "import serial; s=serial.Serial('/dev/ttyUSB0', 115200); print('OK' if s.is_open else 'FAIL')"
```

### Python imports fail
```bash
# Activate venv and reinstall
source ~/horaltscanner_env/bin/activate
pip install --upgrade -r ~/horaltscanner/requirements.txt
```

---

## 🎬 What's Next?

1. **Configure hardware** — Wire everything according to `hardware/wiring_diagram.md`
2. **Test controls** — Use web dashboard to verify lasers, motors, fans
3. **Calibrate** — Home axes and test movement ranges
4. **Add cameras** — Integrate USB camera and Pi Camera V3
5. **Run scans** — Use scanner engine for 3D capture
6. **Process data** — 3D reconstruction with Open3D

---

## 📚 Documentation

- **Main README:** `README.md`
- **API Reference:** `USAGE.md`
- **Deployment Guide:** `DEPLOYMENT.md`
- **Hardware Wiring:** `hardware/wiring_diagram.md`
- **USB Protocol:** `docs/usb_protocol.md`
- **Changelog:** `CHANGELOG.md`

---

## 💡 Tips

- **SSH Access:** Add `~/.ssh/id_rsa.pub` to `/home/pi/.ssh/authorized_keys` for passwordless login
- **Hostname:** Change with `sudo raspi-config` → System Options → Hostname
- **WiFi:** Configure with `sudo raspi-config` → System Options → Wireless LAN
- **Automatic Updates:** Enable with `sudo apt-get install -y unattended-upgrades`
- **Backups:** Automatically created in `/home/pi/backups/`

---

## ❓ Getting Help

1. Check `TROUBLESHOOTING` section above
2. Review service logs: `sudo journalctl -u horalscanner -f`
3. Test manually: `python software/api/horalscanner_api.py`
4. GitHub Issues: https://github.com/jose33bro/horaltscanner/issues

---

## ✅ Checklist

- [ ] Raspberry Pi 4 with Raspberry Pi OS installed
- [ ] SSH access working
- [ ] HoralScanner code cloned
- [ ] Python venv created and activated
- [ ] Dependencies installed (requirements.txt)
- [ ] systemd service configured
- [ ] Service running (`sudo systemctl status horalscanner`)
- [ ] Web dashboard accessible on port 5000
- [ ] Hardware wired according to documentation
- [ ] GPIO and STM32 drivers showing as connected
- [ ] Tested at least one API endpoint (laser, LED, motor)

---

**Installation complete!** 🎉

Your Raspberry Pi is now running HoralScanner. Access the dashboard at:
```
http://<your-pi-ip>:5000
```

Enjoy your 3D scanner! 📸🔴✨

---

*Last updated: $(date)*
*HoralScanner v1.0.0*

EOF

cat QUICK_START.md
