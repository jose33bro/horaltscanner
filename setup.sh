#!/bin/bash
# HoralScanner PRO – Installation script
# Run as: bash setup.sh
set -e

INSTALL_DIR="${INSTALL_DIR:-/home/pi/horaltscanner}"
VENV_DIR="${VENV_DIR:-/home/pi/horaltscanner_env}"
SERVICE_USER="${SERVICE_USER:-pi}"
LOG_DIR="/var/log/horalscanner"

echo "╔══════════════════════════════════════════════╗"
echo "║     HoralScanner PRO – Installation           ║"
echo "╚══════════════════════════════════════════════╝"

# 1. System dependencies
echo "[1/8] Installing system dependencies…"
sudo apt-get update -q
sudo apt-get install -y \
  python3-dev python3-venv python3-pip \
  libblas-dev liblapack-dev libopenblas-dev \
  libgl1-mesa-glx libglib2.0-0 \
  git curl v4l-utils \
  prusa-slicer || true   # prusa-slicer may not be in all repos

# 2. Virtual environment
echo "[2/8] Creating Python virtual environment at ${VENV_DIR}…"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

# 3. Python dependencies
echo "[3/8] Installing Python dependencies…"
pip install --upgrade pip --quiet
pip install \
  flask flask-cors \
  open3d \
  numpy opencv-python-headless Pillow \
  requests \
  gpiozero \
  pyserial \
  numpy-stl \
  picamera2 || true   # picamera2 only on Pi

# 4. Create log directory
echo "[4/8] Creating log directory…"
sudo mkdir -p "${LOG_DIR}"
sudo chown "${SERVICE_USER}:${SERVICE_USER}" "${LOG_DIR}"

# 5. Create backups directory
echo "[5/8] Creating backups directory…"
mkdir -p "${INSTALL_DIR}/backups"

# 6. systemd service
echo "[6/8] Installing systemd service…"
sudo tee /etc/systemd/system/horalscanner.service > /dev/null << SERVICE
[Unit]
Description=HoralScanner 3D Scanner API
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV_DIR}/bin/python3 ${INSTALL_DIR}/software/api/horalscanner_api.py
Restart=on-failure
RestartSec=10
StandardOutput=append:${LOG_DIR}/horalscanner.log
StandardError=append:${LOG_DIR}/horalscanner.log

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable horalscanner
sudo systemctl restart horalscanner

# 7. Cron job for auto-update (every hour)
echo "[7/8] Setting up auto-update cron job…"
(crontab -l 2>/dev/null | grep -v horalscanner; \
 echo "0 * * * * cd ${INSTALL_DIR} && git pull origin main --quiet && ${VENV_DIR}/bin/pip install -r requirements.txt --quiet && sudo systemctl restart horalscanner") \
 | crontab -

# 8. Done
echo "[8/8] Done!"
echo ""
echo "✅ HoralScanner PRO installation complete!"
echo "   API URL : http://$(hostname -I | awk '{print $1}'):5000"
echo "   Logs    : ${LOG_DIR}/horalscanner.log"
echo "   Update  : bash ${INSTALL_DIR}/software/scripts/update.sh"
