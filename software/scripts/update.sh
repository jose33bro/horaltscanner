#!/bin/bash
# HoralScanner PRO – Update script
set -e

INSTALL_DIR="${INSTALL_DIR:-/home/pi/horaltscanner}"
VENV_DIR="${VENV_DIR:-/home/pi/horaltscanner_env}"
BACKUP_DIR="${INSTALL_DIR}/backups"

echo "⬆️  HoralScanner PRO – Update"

# Backup
STAMP=$(date +%Y%m%d_%H%M%S)
echo "📦 Backing up to ${BACKUP_DIR}/backup_${STAMP}.tar.gz …"
mkdir -p "${BACKUP_DIR}"
tar -czf "${BACKUP_DIR}/backup_${STAMP}.tar.gz" \
    -C "${INSTALL_DIR}" \
    --exclude='.git' --exclude='backups' --exclude='__pycache__' \
    . 2>/dev/null || true

# Git pull
echo "🔄 git pull…"
cd "${INSTALL_DIR}"
git pull origin main

# Pip install
echo "📦 pip install…"
source "${VENV_DIR}/bin/activate"
pip install -r requirements.txt --quiet

# Restart service
echo "🔁 Restarting service…"
sudo systemctl restart horalscanner

echo "✅ Update complete – $(date)"
