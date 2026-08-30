# HoralScanner — Deployment Guide

## System Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Raspberry Pi OS (Bullseye/Bookworm) or any Debian-based Linux |
| Python | 3.9 + |
| Hardware | Raspberry Pi 4 (recommended) + Creality V4.2.2 board via USB |
| Network | Local LAN access on port 5000 |

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/jose33bro/horaltscanner.git
cd horaltscanner
```

### 2. Create a virtual environment

```bash
python3 -m venv ~/horaltscanner_env
source ~/horaltscanner_env/bin/activate
```

### 3. Install dependencies

```bash
pip install flask gpiozero pyserial
```

### 4. Verify hardware connections

- Raspberry Pi GPIO pins wired as per `hardware/wiring_diagram.md`
- Creality V4.2.2 board connected via USB (`/dev/ttyUSB0` or `/dev/ttyACM0`)

### 5. Test manually

```bash
python software/api/horalscanner_api.py
```

Open `http://<raspberry-pi-ip>:5000` in a browser — you should see the dashboard.

## systemd Service Configuration

The service file lives at `/etc/systemd/system/horalscanner.service`.

### Example service file

```ini
[Unit]
Description=HoralScanner 3D Scanner API
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/horaltscanner
ExecStart=/home/pi/horaltscanner_env/bin/python software/api/horalscanner_api.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable horalscanner
sudo systemctl start horalscanner
sudo systemctl status horalscanner
```

### Check logs

```bash
sudo journalctl -u horalscanner -f
```

## Updating

```bash
cd ~/horaltscanner
git pull origin main
sudo systemctl restart horalscanner
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` | Another process on port 5000 | `sudo lsof -i :5000` and kill it |
| `GPIO driver unavailable` | Missing `gpiozero` or wrong user | Install gpiozero; add user to `gpio` group |

### Open3D sur Raspberry Pi OS 64 bits

PyPI ne publie pas de roue Open3D 0.19.0 pour Linux `aarch64`. Le dépôt fournit
donc un installateur qui compile les sources officielles sans interface
graphique:

```bash
cd /home/pi/horaltscanner
bash software/scripts/install_open3d_pi.sh
sudo systemctl restart horalscanner
```

La compilation utilise deux tâches par défaut pour limiter la mémoire sur le
Raspberry Pi. Cette valeur peut être ajustée avec `OPEN3D_BUILD_JOBS`.

Documentation officielle:
https://github.com/isl-org/Open3D/blob/v0.19.0/docs/arm.rst
| `STM32 driver unavailable` | USB not connected / wrong port | Check `dmesg | grep tty`; update serial port in config |
| `Failed to read board temperature` | STM32 not responding | Verify firmware is flashed and USB cable is data-capable |
| Service crashes at startup | Python import error | Check `journalctl -u horalscanner -n 50` for traceback |
