#!/bin/bash
# HoralScanner — Clean Pi Update (Remove Klipper, Install HoralScanner)
# Run this to completely replace Klipper with HoralScanner on existing Pi

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${BLUE}ℹ ${1}${NC}"; }
log_success() { echo -e "${GREEN}✓ ${1}${NC}"; }
log_warn() { echo -e "${YELLOW}⚠ ${1}${NC}"; }
log_error() { echo -e "${RED}✗ ${1}${NC}"; }

echo ""
echo "╔═════════════════════════════════════════════════════════════╗"
echo "║     HoralScanner — Complete Pi Update (Clean Install)      ║"
echo "║         Removes Klipper/Marlin • Installs USB API         ║"
echo "╚═════════════════════════════════════════════════════════════╝"
echo ""

if [ "$EUID" -ne 0 ]; then
    log_error "Must run with sudo"
    exit 1
fi

# STEP 1: Stop all services
stop_services() {
    log_info "Stopping all services..."
    systemctl stop klipper 2>/dev/null || true
    systemctl stop moonraker 2>/dev/null || true
    systemctl stop nginx 2>/dev/null || true
    systemctl stop horalscanner 2>/dev/null || true
    log_success "Services stopped"
}

# STEP 2: Disable services
disable_services() {
    log_info "Disabling legacy services..."
    systemctl disable klipper 2>/dev/null || true
    systemctl disable moonraker 2>/dev/null || true
    systemctl disable nginx 2>/dev/null || true
    log_success "Services disabled"
}

# STEP 3: Backup everything
backup_system() {
    log_info "Creating backup..."
    BACKUP_DIR="/home/pi/backups_old_system_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    [ -d "/home/pi/klipper" ] && cp -r "/home/pi/klipper" "$BACKUP_DIR/" || true
    [ -d "/home/pi/klipper_config" ] && cp -r "/home/pi/klipper_config" "$BACKUP_DIR/" || true
    [ -d "/home/pi/moonraker" ] && cp -r "/home/pi/moonraker" "$BACKUP_DIR/" || true
    [ -d "/home/pi/mainsail" ] && cp -r "/home/pi/mainsail" "$BACKUP_DIR/" || true
    [ -d "/home/pi/fluidd" ] && cp -r "/home/pi/fluidd" "$BACKUP_DIR/" || true
    
    log_success "Backup saved to: $BACKUP_DIR"
}

# STEP 4: Remove Klipper
remove_klipper() {
    log_info "Removing Klipper..."
    rm -rf /home/pi/klipper
    rm -rf /home/pi/klipper_config
    rm -rf /home/pi/klipper_logs
    rm -f /etc/systemd/system/klipper.service
    log_success "Klipper removed"
}

# STEP 5: Remove Moonraker
remove_moonraker() {
    log_info "Removing Moonraker..."
    rm -rf /home/pi/moonraker
    rm -rf /home/pi/moonraker_logs
    rm -f /etc/systemd/system/moonraker.service
    log_success "Moonraker removed"
}

# STEP 6: Remove web UIs
remove_web_ui() {
    log_info "Removing Mainsail/Fluidd..."
    rm -rf /home/pi/mainsail
    rm -rf /home/pi/fluidd
    rm -rf /var/www/html/*
    rm -f /etc/nginx/sites-enabled/mainsail
    rm -f /etc/nginx/sites-enabled/fluidd
    log_success "Web UIs removed"
}

# STEP 7: Remove Nginx
remove_nginx() {
    log_info "Removing Nginx..."
    systemctl stop nginx 2>/dev/null || true
    systemctl disable nginx 2>/dev/null || true
    apt-get remove -y nginx 2>/dev/null || log_warn "Nginx not installed"
    log_success "Nginx removed"
}

# STEP 8: Clean old venv
clean_old_venv() {
    log_info "Cleaning old Python environments..."
    rm -rf /home/pi/.virtualenvs 2>/dev/null || true
    rm -rf /home/pi/.env 2>/dev/null || true
    rm -rf /home/pi/printer_data 2>/dev/null || true
    log_success "Old environments cleaned"
}

# STEP 9: Update system
update_system() {
    log_info "Updating Raspberry Pi OS..."
    apt-get update
    apt-get upgrade -y
    apt-get autoremove -y
    log_success "System updated"
}

# STEP 10: Install dependencies
install_dependencies() {
    log_info "Installing dependencies..."
    apt-get install -y \
        python3 python3-pip python3-venv \
        build-essential python3-dev \
        libopencv-dev python3-opencv \
        git curl wget \
        libatlas-base-dev libjasper-dev \
        libharfbuzz0b libwebp6 libtiff5 libopenjp2-7 \
        libopenblas-dev liblapack-dev \
        i2c-tools usbutils
    
    log_success "Dependencies installed"
}

# STEP 11: Configure GPIO
configure_gpio() {
    log_info "Configuring GPIO access..."
    usermod -a -G gpio pi 2>/dev/null || true
    usermod -a -G dialout pi 2>/dev/null || true
    
    # Enable I2C, SPI, UART in /boot/firmware/config.txt
    if [ -f "/boot/firmware/config.txt" ]; then
        sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' /boot/firmware/config.txt || true
        sed -i 's/^#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt || true
        sed -i 's/^#enable_uart=1/enable_uart=1/' /boot/firmware/config.txt || true
    fi
    
    log_success "GPIO configured"
}

# STEP 12: Clone/update HoralScanner
install_horaltscanner() {
    log_info "Installing HoralScanner..."
    
    if [ -d "/home/pi/horaltscanner" ]; then
        log_warn "HoralScanner already exists, updating..."
        cd /home/pi/horaltscanner
        git pull origin main
    else
        git clone https://github.com/jose33bro/horaltscanner.git /home/pi/horaltscanner
    fi
    
    # Create venv
    python3 -m venv /home/pi/horaltscanner_env
    source /home/pi/horaltscanner_env/bin/activate
    
    # Install Python deps
    log_info "Installing Python packages (this takes ~10 minutes)..."
    pip install --upgrade pip setuptools wheel
    pip install -r /home/pi/horaltscanner/requirements.txt
    
    deactivate
    
    # Fix ownership
    chown -R pi:pi /home/pi/horaltscanner
    chown -R pi:pi /home/pi/horaltscanner_env
    
    log_success "HoralScanner installed"
}

# STEP 13: Install systemd service
install_service() {
    log_info "Installing HoralScanner systemd service..."
    
    cat > /etc/systemd/system/horalscanner.service <<'SERVICE_EOF'
[Unit]
Description=HoralScanner 3D Scanner API
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/horaltscanner
Environment="PATH=/home/pi/horaltscanner_env/bin"
ExecStart=/home/pi/horaltscanner_env/bin/python /home/pi/horaltscanner/software/api/horalscanner_api.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=horalscanner

[Install]
WantedBy=multi-user.target
SERVICE_EOF

    systemctl daemon-reload
    systemctl enable horalscanner
    
    log_success "HoralScanner service installed"
}

# STEP 14: Clean up
cleanup() {
    log_info "Cleaning up..."
    
    apt-get clean
    apt-get autoremove -y
    rm -rf /tmp/*
    rm -f /home/pi/printer.cfg
    
    log_success "Cleanup complete"
}

# STEP 15: Summary
summary() {
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║       ✅ Pi Update Complete - Ready to Reboot         ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "🗑️  Removed:"
    echo "   ✗ Klipper"
    echo "   ✗ Moonraker"
    echo "   ✗ Mainsail/Fluidd"
    echo "   ✗ Nginx"
    echo ""
    echo "✅ Installed:"
    echo "   ✓ HoralScanner Flask API (port 5000)"
    echo "   ✓ Python 3.9+ environment"
    echo "   ✓ systemd auto-start service"
    echo "   ✓ All dependencies"
    echo ""
    echo "📦 Backup saved to:"
    echo "   /home/pi/backups_old_system_*"
    echo ""
    echo "🚀 Next: Reboot your Pi"
    echo "   ${BLUE}sudo reboot${NC}"
    echo ""
    echo "After reboot:"
    echo "   ✓ Check service: ${BLUE}sudo systemctl status horalscanner${NC}"
    echo "   ✓ View logs: ${BLUE}sudo journalctl -u horalscanner -f${NC}"
    echo "   ✓ Access dashboard: ${BLUE}http://<your-pi-ip>:5000${NC}"
    echo ""
}

# MAIN EXECUTION
main() {
    log_warn "This will COMPLETELY remove Klipper and replace with HoralScanner"
    echo ""
    log_warn "Your Pi will:"
    echo "   • Stop all Klipper/Moonraker services"
    echo "   • Backup old config to /home/pi/backups_old_system_*"
    echo "   • Remove Klipper, Moonraker, Mainsail, Nginx"
    echo "   • Install HoralScanner with Flask API"
    echo "   • Reboot and run on port 5000"
    echo ""
    read -p "Continue? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log_error "Cancelled"
        exit 0
    fi
    
    echo ""
    
    stop_services
    disable_services
    backup_system
    remove_klipper
    remove_moonraker
    remove_web_ui
    remove_nginx
    clean_old_venv
    update_system
    install_dependencies
    configure_gpio
    install_horaltscanner
    install_service
    cleanup
    
    summary
    
    echo ""
    read -p "Reboot now? (yes/no): " reboot_confirm
    if [ "$reboot_confirm" = "yes" ]; then
        log_info "Rebooting..."
        sleep 2
        reboot
    fi
}

main
