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
cd software
python -m api.horalscanner_api
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
WorkingDirectory=/home/pi/horaltscanner/software
ExecStart=/home/pi/horaltscanner_env/bin/python -m api.horalscanner_api
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

## Production Server (Gunicorn)

The Flask development server (`python -m api.horalscanner_api`) is
**single-threaded and unsuitable for production**: it handles one HTTP
request at a time, so while a client is streaming an MJPEG preview or
polling `/api/model/status`, every other request (scan control, status
checks, UI page loads) is blocked. Even though 3D reconstruction now runs
on a background thread and returns immediately, the dev server itself
cannot serve multiple *concurrent* requests, which limits the benefit of
that async work.

For production/RPi4 deployments, run the API behind
[Gunicorn](https://gunicorn.org/) with the `gevent` worker class, which
gives cooperative, non-blocking concurrency well suited to a Raspberry Pi's
limited CPU cores:

```bash
pip install -r requirements.txt  # installs gunicorn + gevent
cd software
gunicorn --workers 4 --worker-class gevent --bind 0.0.0.0:5000 "api:create_app()"
```

- `--workers 4`: 4 worker processes let the API accept and answer several
  requests (status polling, camera preview, UI) at once instead of queuing
  behind a single-threaded dev server.
- `--worker-class gevent`: cooperative greenlets inside each worker so
  blocking I/O (camera reads, file responses) doesn't stall other
  in-flight requests on that worker.

### systemd service using Gunicorn

Update the `ExecStart` line in the service file above to use Gunicorn
instead of the Flask dev server:

```ini
ExecStart=/home/pi/horaltscanner_env/bin/gunicorn --workers 4 --worker-class gevent --bind 0.0.0.0:5000 "api:create_app()"
```

Then reload and restart as usual:

```bash
sudo systemctl daemon-reload
sudo systemctl restart horalscanner
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
