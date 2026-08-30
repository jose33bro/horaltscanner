# HoralScanner

**Modular 3D Scanner & Reconstruction System**  
Raspberry Pi 4 + Creality V4.2.2 with custom USB firmware

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Raspberry Pi](https://img.shields.io/badge/RPi-4-red)

---

## 🎯 What is HoralScanner?

HoralScanner is a complete **3D scanning and reconstruction system** built from the ground up for **Raspberry Pi 4**. It uses:

✅ **Custom STM32 USB firmware** — Direct motor/stepper control via USB CDC protocol  
✅ **Flask REST API** — Lightweight web service on port 5000  
✅ **Multi-sensor fusion** — Lidar (TF-Luna) + dual lasers + cameras (USB + DSI)  
✅ **3D reconstruction** — Open3D-powered point cloud processing  
✅ **Web dashboard** — Real-time control & monitoring  
✅ **Systemd auto-start** — Service runs on boot  

Perfect for:
- 🔬 Academic 3D scanning research
- 🖨️ Retrofitting old 3D printers
- 🎓 Educational robotics projects
- 🏭 Industrial inspection systems

---

## 🚀 Quick Start (Choose Your Path)

### Path A: Fresh Raspberry Pi OS (Recommended)
```bash
# 1. Flash latest Raspberry Pi OS to SD card
# Download: https://www.raspberrypi.com/software/

# 2. SSH into your Pi
ssh pi@raspberrypi.local

# 3. One-line installation
sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/setup_pi.sh | bash"

# 4. Reboot
sudo reboot

# 5. Access dashboard
# Open browser: http://<your-pi-ip>:5000
```
**Time:** 30-45 minutes | **Difficulty:** ⭐ Easy

---

### Path B: Manual Setup
See [QUICK_START.md](QUICK_START.md) for step-by-step instructions.

---

## 📊 Web Dashboard

Access at: `http://<your-pi-ip>:5000`

**Features:**
- 🔴 **Lasers:** Toggle left/right laser
- 🟡 **LED RGB:** Color picker + presets
- ⚙️ **Motors:** Move X/Y/Z by mm, homing, stop
- 💨 **Fans:** Control Pi/Creality/temperature fans (0-100%)
- 🌡️ **Temperature:** Real-time board sensor reading
- 📡 **Status:** GPIO & STM32 driver health

---

## 🔌 Hardware Setup

**Required:**
- Raspberry Pi 4 (4GB+)
- Creality V4.2.2 board (STM32F103RET6)
- USB cable (Micro-B, data-capable)
- Power supply

**GPIO Mapping (Raspberry Pi):**
```
GPIO27  → Laser Left (digital)
GPIO22  → Laser Right (digital)
GPIO18  → LED Red (PWM)
GPIO13  → LED Green (PWM)
GPIO19  → LED Blue (PWM)
GPIO23  → Pi Fan (PWM)
```

**STM32F103 Mapping (Creality V4.2.2):**
```
PC2/PB9/PC3  → Stepper X (step/dir/enable)
PB8/PB7/PC3  → Stepper Y (step/dir/enable)
PB6/PB5/PC3  → Stepper Z (step/dir/enable)
PA0          → Creality Fan (PWM)
PA8          → Temperature Fan (PWM)
PC5          → Board Temp Sensor
```

See `hardware/wiring_diagram.md` for complete pinout.

---

## 📡 REST API

All endpoints return JSON. Base URL: `http://<your-pi-ip>:5000`

### Lasers
```bash
POST /api/laser/left       {"state": true}      # Turn ON
POST /api/laser/right      {"state": false}     # Turn OFF
GET  /api/laser/status                          # Get both status
```

### LED
```bash
POST /api/led/color        {"r": 255, "g": 0, "b": 0}  # Set to red
GET  /api/led/status                            # Get current color
```

### Motors
```bash
POST /api/move/x           {"mm": 10.0}         # Move X by 10mm
POST /api/home/x                                # Home X axis
POST /api/home/all                              # Home all axes
POST /api/motor/stop       {"axis": "z"}        # Stop Z motor
GET  /api/motor/status                          # Get positions
```

### Fans
```bash
POST /api/fan/pi           {"percent": 50}      # Set Pi fan to 50%
POST /api/fan/creality     {"speed": 0.75}      # Set Creality fan
POST /api/fan/temperature  {"pwm": 0.5}         # Set temp fan
GET  /api/fan/status                            # Get all speeds
```

### Temperature
```bash
GET  /api/temperature/board                     # Get °C
GET  /api/temperature/all                       # Get all sensors
```

### System
```bash
GET  /api/status                                # Health check
GET  /                                          # Web dashboard
```

**Full API Reference:** See [USAGE.md](USAGE.md)

---

## 📁 Project Structure

```
horaltscanner/
├── software/
│   ├── api/                    # Flask API server
│   │   ├── horalscanner_api.py # Main entry point (port 5000)
│   │   ├── motor_control.py    # X/Y/Z axis orchestration
│   │   ├── laser_control.py    # GPIO laser control
│   │   ├── led_control.py      # RGB LED control
│   │   ├── camera_driver.py    # USB & Pi Camera capture
│   │   ├── lidar_driver.py     # TF-Luna lidar driver
│   │   └── scanner_engine.py   # Multi-sensor scan orchestration
│   │
│   ├── web/                    # Web dashboard (HTML/CSS/JS)
│   │   ├── index.html
│   │   ├── app.js
│   │   └── style.css
│   │
│   ├── drivers/                # Hardware abstraction
│   │   ├── stm32_driver.py     # Creality USB interface
│   │   └── gpio_driver.py      # Raspberry Pi GPIO
│   │
│   ├── scripts/                # Utilities
│   │   └── update.sh           # Auto-update script
│   │
│   └── tests/                  # Test suite
│       └── test_*.py
│
├── firmware/
│   ├── creality_v422/
│   │   └── usb_firmware.c      # STM32F103 firmware (custom USB protocol)
│   │
│   └── raspberry_pi/
│       ├── usb_driver.py       # Python USB CDC driver
│       ├── motor_control.py    # Motor orchestration
│       ├── camera_acquisition.py
│       ├── lidar_acquisition.py
│       └── scanner_app.py      # Main scanning app
│
├── hardware/
│   ├── wiring_diagram.md       # GPIO & pin mappings
│   └── README.md
│
├── docs/
│   └── usb_protocol.md         # USB CDC protocol spec
│
├── setup_pi.sh                 # Complete Pi setup script
├── QUICK_START.md              # Installation guide (3 paths)
├── DEPLOYMENT.md               # Production deployment guide
├── USAGE.md                    # API reference & examples
├── CHANGELOG.md                # Version history
├── requirements.txt            # Python dependencies
└── VERSION                     # Version number
```

---

## 🛠️ Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | Python 3.9+ (69%) | Backend, drivers, scanning logic |
| **Web Framework** | Flask 2.3+ | REST API server |
| **Hardware I/O** | RPi.GPIO, gpiozero | GPIO control |
| **USB/Serial** | pyserial | STM32 communication |
| **Vision** | OpenCV 4.5+ | Camera capture, image processing |
| **3D** | Open3D 0.12+ | Point cloud reconstruction |
| **Math** | NumPy, SciPy | Scientific computing |
| **Frontend** | Vanilla JS, HTML5, CSS3 | Web dashboard |
| **Init** | systemd | Service management |
| **OS** | Raspberry Pi OS (Bookworm) | Base system |

---

## 📋 Scripts Included

### `setup_pi.sh` — Full Setup
```bash
sudo bash setup_pi.sh --full          # Fresh system + code + service
sudo bash setup_pi.sh --install       # Skip system updates
sudo bash setup_pi.sh --update        # Update code only
sudo bash setup_pi.sh --quick-test    # Test imports
```

### `software/scripts/update.sh` — Auto-Update
```bash
bash /home/pi/horaltscanner/software/scripts/update.sh
```
- Backs up current state
- Pulls latest code
- Updates Python deps
- Restarts service

---

## ✅ Verification Checklist

After installation, verify:

- [ ] SSH access to Pi works
- [ ] Service running: `sudo systemctl status horalscanner`
- [ ] Web dashboard loads: `http://<pi-ip>:5000`
- [ ] GPIO driver connected (in dashboard Status card)
- [ ] STM32 driver connected (when board is powered)
- [ ] Can toggle laser via dashboard or API
- [ ] Can read board temperature
- [ ] Can move motors (after homing)

---

## 🐛 Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u horalscanner -n 50

# If GPIO fails
sudo usermod -a -G gpio pi
sudo reboot
```

### Can't connect to Creality board
```bash
# List serial devices
ls /dev/tty*

# Check USB
lsusb
dmesg | grep -i stm32
```

### Port 5000 in use
```bash
sudo lsof -i :5000
sudo kill -9 <PID>
```

Full troubleshooting: See [DEPLOYMENT.md](DEPLOYMENT.md) or [QUICK_START.md](QUICK_START.md)

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| [QUICK_START.md](QUICK_START.md) | 3 installation paths, setup verification |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Production deployment, systemd, troubleshooting |
| [USAGE.md](USAGE.md) | Full API reference with cURL examples |
| [CHANGELOG.md](CHANGELOG.md) | Version history and release notes |
| `hardware/wiring_diagram.md` | Complete GPIO & pin mappings |
| `docs/usb_protocol.md` | USB CDC protocol specification |

---

## 🔐 Security Notes

⚠️ **This project is for local development/research:**

- Default user: `pi` / password: `raspberry` (change immediately!)
- API has no authentication (designed for LAN only)
- No HTTPS (use only on trusted networks)
- GPIO access available to `pi` user

For production deployment:
1. Change default password
2. Disable SSH password auth (use keys only)
3. Use firewall (ufw)
4. Add reverse proxy with authentication
5. Use VPN for remote access

---

## 📈 Performance

Typical performance on Raspberry Pi 4 (4GB):

| Task | Performance |
|------|-------------|
| API response time | <50ms |
| Motor command | 10-50ms |
| GPIO toggle | 1-5ms |
| Camera capture | 30-60fps (640x480) |
| Lidar scan | 5Hz (200pt/s) |
| 3D reconstruction | 1-5 min for 1000+ points |

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📞 Support

- **Issues:** https://github.com/jose33bro/horaltscanner/issues
- **Discussions:** https://github.com/jose33bro/horaltscanner/discussions

---

## 🎉 Status

- ✅ **v1.0.0** — Stable release
  - Web dashboard
  - Flask API
  - GPIO/STM32 drivers
  - Systemd service
  - Full documentation

---

**Made with ❤️ for 3D scanning enthusiasts**

Get started now: [QUICK_START.md](QUICK_START.md)
