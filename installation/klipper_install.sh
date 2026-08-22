#!/bin/bash
# ============================================================
# Script d'installation Klipper - Horaltscanner
# Pour Raspberry Pi 4 (4Go) avec Creality V4.2.2 via USB
# OS: Raspbian Bullseye (64-bit recommandé)
# ============================================================

set -e

KLIPPER_USER="pi"
KLIPPER_HOME="/home/${KLIPPER_USER}"
GCODE_DIR="${KLIPPER_HOME}/gcode_files"

echo "============================================"
echo "  Installation Klipper - Horaltscanner"
echo "============================================"

# ============================================================
# 1. Mise à jour du système
# ============================================================
echo "[1/8] Mise à jour du système..."
sudo apt-get update && sudo apt-get upgrade -y

# Dépendances système
sudo apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-virtualenv \
    virtualenv \
    libffi-dev \
    build-essential \
    libncurses-dev \
    libusb-dev \
    avrdude \
    gcc-arm-none-eabi \
    binutils-arm-none-eabi \
    libnewlib-arm-none-eabi \
    stm32flash \
    dfu-util \
    curl \
    wget \
    nginx \
    iproute2 \
    rfkill \
    iw

echo "[1/8] ✓ Système mis à jour"

# ============================================================
# 2. Installation de Klipper
# ============================================================
echo "[2/8] Installation de Klipper..."

if [ ! -d "${KLIPPER_HOME}/klipper" ]; then
    cd "${KLIPPER_HOME}"
    git clone https://github.com/Klipper3d/klipper.git
else
    echo "  Klipper déjà installé, mise à jour..."
    cd "${KLIPPER_HOME}/klipper"
    git pull
fi

# Créer l'environnement virtuel Python
cd "${KLIPPER_HOME}/klipper"
virtualenv -p python3 "${KLIPPER_HOME}/klippy-env"
"${KLIPPER_HOME}/klippy-env/bin/pip" install -r scripts/klippy-requirements.txt

echo "[2/8] ✓ Klipper installé"

# ============================================================
# 3. Installation de Moonraker (API)
# ============================================================
echo "[3/8] Installation de Moonraker..."

if [ ! -d "${KLIPPER_HOME}/moonraker" ]; then
    cd "${KLIPPER_HOME}"
    git clone https://github.com/Arksine/moonraker.git
else
    echo "  Moonraker déjà installé, mise à jour..."
    cd "${KLIPPER_HOME}/moonraker"
    git pull
fi

cd "${KLIPPER_HOME}/moonraker"
virtualenv -p python3 "${KLIPPER_HOME}/moonraker-env"
"${KLIPPER_HOME}/moonraker-env/bin/pip" install -r scripts/moonraker-requirements.txt

echo "[3/8] ✓ Moonraker installé"

# ============================================================
# 4. Installation de Mainsail (Interface web)
# ============================================================
echo "[4/8] Installation de Mainsail..."

MAINSAIL_DIR="/var/www/html/mainsail"
sudo mkdir -p "${MAINSAIL_DIR}"

MAINSAIL_VERSION=$(curl -s "https://api.github.com/repos/mainsail-crew/mainsail/releases/latest" | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
sudo wget -q "https://github.com/mainsail-crew/mainsail/releases/download/${MAINSAIL_VERSION}/mainsail.zip" -O /tmp/mainsail.zip
sudo unzip -o /tmp/mainsail.zip -d "${MAINSAIL_DIR}"
sudo rm /tmp/mainsail.zip

echo "[4/8] ✓ Mainsail installé (version ${MAINSAIL_VERSION})"

# ============================================================
# 5. Configuration des répertoires
# ============================================================
echo "[5/8] Configuration des répertoires..."

# Répertoire de configuration Klipper
mkdir -p "${KLIPPER_HOME}/printer_data/config"
mkdir -p "${KLIPPER_HOME}/printer_data/logs"
mkdir -p "${KLIPPER_HOME}/printer_data/gcodes"
mkdir -p "${GCODE_DIR}"

# Copier les configurations du scanner
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

if [ -d "${REPO_ROOT}/klipper_config" ]; then
    cp "${REPO_ROOT}/klipper_config/"*.cfg "${KLIPPER_HOME}/printer_data/config/"
    echo "  Configurations du scanner copiées"
fi

echo "[5/8] ✓ Répertoires configurés"

# ============================================================
# 6. Configuration des services systemd
# ============================================================
echo "[6/8] Configuration des services systemd..."

# Service Klipper
sudo tee /etc/systemd/system/klipper.service > /dev/null << 'EOF'
[Unit]
Description=Klipper 3D Printer Firmware SVC
After=syslog.target network-online.target

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=pi
RemainAfterExit=yes
ExecStart=/home/pi/klippy-env/bin/python /home/pi/klipper/klippy/klippy.py /home/pi/printer_data/config/printer.cfg -l /home/pi/printer_data/logs/klippy.log -a /tmp/klippy_uds
Restart=always
RestartSec=10
EOF

# Service Moonraker
sudo tee /etc/systemd/system/moonraker.service > /dev/null << 'EOF'
[Unit]
Description=API Server for Klipper SVC
After=network-online.target klipper.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=pi
RemainAfterExit=yes
ExecStart=/home/pi/moonraker-env/bin/python /home/pi/moonraker/moonraker/moonraker.py -d /home/pi/printer_data
Restart=always
RestartSec=10
EOF

# Configuration Moonraker
tee "${KLIPPER_HOME}/printer_data/config/moonraker.conf" > /dev/null << 'EOF'
[server]
host: 0.0.0.0
port: 7125
klippy_uds_address: /tmp/klippy_uds

[authorization]
trusted_clients:
    127.0.0.0/8
    10.0.0.0/8
    169.254.0.0/16
    172.16.0.0/12
    192.168.0.0/16
    FE80::/10
    ::1/128
cors_domains:
    *.lan
    *.local
    *://my.mainsail.xyz
    *://app.fluidd.xyz

[octoprint_compat]

[history]

[virtual_sdcard]
path: /home/pi/gcode_files

[file_manager]
enable_object_processing: False
EOF

sudo systemctl daemon-reload
sudo systemctl enable klipper moonraker
echo "[6/8] ✓ Services systemd configurés"

# ============================================================
# 7. Configuration Nginx pour Mainsail
# ============================================================
echo "[7/8] Configuration Nginx..."

sudo tee /etc/nginx/sites-available/mainsail > /dev/null << 'EOF'
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream apiserver {
    ip_hash;
    server 127.0.0.1:7125;
}

server {
    listen 80 default_server;
    access_log /var/log/nginx/mainsail-access.log;
    error_log /var/log/nginx/mainsail-error.log;

    client_max_body_size 512M;

    root /var/www/html/mainsail;
    index index.html;
    server_name _;

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_proxied expired no-cache no-store private auth;
    gzip_comp_level 4;
    gzip_buffers 16 8k;
    gzip_http_version 1.1;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/json application/xml;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /websocket {
        proxy_pass http://apiserver/websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }

    location ~* ^/api(?:/.*)?$ {
        proxy_pass http://apiserver$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/mainsail /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx

echo "[7/8] ✓ Nginx configuré"

# ============================================================
# 8. Configuration des permissions USB et GPIO
# ============================================================
echo "[8/8] Configuration des permissions..."

# Ajouter l'utilisateur aux groupes nécessaires
sudo usermod -aG dialout,tty,gpio,spi,i2c "${KLIPPER_USER}"

# Règle udev pour Creality V4.2.2 via USB
sudo tee /etc/udev/rules.d/99-creality-v422.rules > /dev/null << 'EOF'
# Creality V4.2.2 - STM32F103RET6 via USB
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="creality_v422", MODE="0666", GROUP="dialout"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[8/8] ✓ Permissions configurées"

# ============================================================
# Fin d'installation
# ============================================================

echo ""
echo "============================================"
echo "  Installation terminée!"
echo "============================================"
echo ""
echo "Prochaines étapes:"
echo ""
echo "1. FLASH le firmware STM32F103 sur la Creality V4.2.2:"
echo "   Voir: installation/mcu_flashing.md"
echo ""
echo "2. Identifier le port USB de la Creality:"
echo "   ls /dev/serial/by-id/"
echo "   Mettre à jour 'serial:' dans klipper_config/creality_v422_usb.cfg"
echo ""
echo "3. Démarrer les services:"
echo "   sudo systemctl start klipper moonraker"
echo ""
echo "4. Accéder à Mainsail:"
echo "   http://$(hostname -I | awk '{print $1}')/"
echo ""
echo "5. Créer le répertoire G-code:"
echo "   mkdir -p ${GCODE_DIR}"
echo ""
echo "Voir la documentation complète: docs/klipper_setup_guide.md"
