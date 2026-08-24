#!/bin/bash
# HoralScanner — Remove Marlin/Klipper and Install Custom STM32 Firmware
# This script removes Klipper/Moonraker and installs HoralScanner's USB firmware

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
echo "║  HoralScanner — Remove Marlin/Klipper & Install Firmware   ║"
echo "╚═════════════════════════════════════════════════════════════╝"
echo ""

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then
    log_error "Must run with sudo"
    exit 1
fi

# Detect OS
DISTRO=$(lsb_release -si)
if [ "$DISTRO" != "Raspbian" ] && [ "$DISTRO" != "Debian" ]; then
    log_warn "Not running on Raspberry Pi OS. Some steps may fail."
fi

# 1. Stop Klipper/Moonraker services
stop_services() {
    log_info "Stopping Klipper/Moonraker services..."
    
    systemctl stop klipper 2>/dev/null || log_warn "Klipper not running"
    systemctl stop moonraker 2>/dev/null || log_warn "Moonraker not running"
    
    # Disable autostart
    systemctl disable klipper 2>/dev/null || true
    systemctl disable moonraker 2>/dev/null || true
    
    log_success "Services stopped"
}

# 2. Backup Klipper configuration
backup_klipper_config() {
    log_info "Backing up Klipper configuration..."
    
    BACKUP_DIR="/home/pi/backups_klipper_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # Backup if exists
    [ -d "/home/pi/klipper" ] && cp -r "/home/pi/klipper" "$BACKUP_DIR/" || true
    [ -d "/home/pi/klipper_config" ] && cp -r "/home/pi/klipper_config" "$BACKUP_DIR/" || true
    [ -d "/home/pi/moonraker" ] && cp -r "/home/pi/moonraker" "$BACKUP_DIR/" || true
    [ -f "/etc/systemd/system/klipper.service" ] && cp "/etc/systemd/system/klipper.service" "$BACKUP_DIR/" || true
    [ -f "/etc/systemd/system/moonraker.service" ] && cp "/etc/systemd/system/moonraker.service" "$BACKUP_DIR/" || true
    
    log_success "Backup created at: $BACKUP_DIR"
}

# 3. Remove Klipper
remove_klipper() {
    log_info "Removing Klipper..."
    
    # Stop and disable
    systemctl stop klipper 2>/dev/null || true
    systemctl disable klipper 2>/dev/null || true
    
    # Remove service file
    rm -f /etc/systemd/system/klipper.service
    
    # Remove directories (but keep backups)
    rm -rf /home/pi/klipper
    rm -rf /home/pi/klipper_logs
    
    log_success "Klipper removed"
}

# 4. Remove Moonraker
remove_moonraker() {
    log_info "Removing Moonraker..."
    
    # Stop and disable
    systemctl stop moonraker 2>/dev/null || true
    systemctl disable moonraker 2>/dev/null || true
    
    # Remove service file
    rm -f /etc/systemd/system/moonraker.service
    
    # Remove directories
    rm -rf /home/pi/moonraker
    rm -rf /home/pi/moonraker_logs
    
    log_success "Moonraker removed"
}

# 5. Remove Mainsail/Fluidd web interfaces
remove_web_ui() {
    log_info "Removing Mainsail/Fluidd web UIs..."
    
    rm -rf /home/pi/mainsail
    rm -rf /home/pi/fluidd
    rm -f /etc/nginx/sites-enabled/mainsail
    rm -f /etc/nginx/sites-enabled/fluidd
    
    log_success "Web UIs removed"
}

# 6. Remove Nginx (no longer needed)
remove_nginx() {
    log_info "Removing Nginx (replaced by Flask)..."
    
    systemctl stop nginx 2>/dev/null || true
    systemctl disable nginx 2>/dev/null || true
    apt-get remove -y nginx 2>/dev/null || log_warn "Nginx not installed"
    
    log_success "Nginx removed"
}

# 7. Install firmware flashing tools
install_firmware_tools() {
    log_info "Installing STM32 firmware flashing tools..."
    
    apt-get update
    apt-get install -y \
        stm32flash \
        arm-none-eabi-gcc \
        arm-none-eabi-binutils \
        python3-pip \
        git \
        libusb-1.0-0 \
        libusb-1.0-0-dev
    
    log_success "Firmware tools installed"
}

# 8. Clone firmware source
clone_firmware() {
    log_info "Cloning HoralScanner firmware..."
    
    FIRMWARE_DIR="/home/pi/horaltscanner_firmware"
    
    if [ -d "$FIRMWARE_DIR" ]; then
        log_warn "Firmware directory already exists. Updating..."
        cd "$FIRMWARE_DIR"
        git pull
    else
        git clone https://github.com/jose33bro/horaltscanner.git "$FIRMWARE_DIR" 2>/dev/null || {
            log_error "Failed to clone repository"
            exit 1
        }
    fi
    
    log_success "Firmware source ready at: $FIRMWARE_DIR"
}

# 9. Compile firmware
compile_firmware() {
    log_info "Compiling STM32F103 firmware..."
    
    FIRMWARE_DIR="/home/pi/horaltscanner_firmware"
    FIRMWARE_SRC="$FIRMWARE_DIR/firmware/creality_v422"
    
    if [ ! -d "$FIRMWARE_SRC" ]; then
        log_error "Firmware source directory not found"
        return 1
    fi
    
    cd "$FIRMWARE_SRC"
    
    # Check for Makefile
    if [ -f "Makefile" ]; then
        make clean 2>/dev/null || true
        make -j4 || {
            log_warn "Firmware compilation had issues. Check output above."
            log_warn "You may need to manually compile with ARM toolchain"
        }
    elif [ -f "CMakeLists.txt" ]; then
        mkdir -p build
        cd build
        cmake ..
        make -j4 || {
            log_warn "Firmware compilation had issues. Check output above."
        }
    else
        log_warn "No Makefile or CMakeLists.txt found in $FIRMWARE_SRC"
        log_warn "You may need to compile firmware manually"
    fi
    
    log_success "Firmware compilation attempt complete"
}

# 10. Flash firmware to STM32
flash_firmware() {
    log_info "Preparing to flash firmware to Creality V4.2.2..."
    echo ""
    log_warn "⚠️  IMPORTANT FLASHING INSTRUCTIONS:"
    echo ""
    echo "1. Disconnect the Creality board from power"
    echo "2. Connect Creality V4.2.2 board via USB to Raspberry Pi"
    echo "3. Put board in bootloader mode (press RESET, then hold BOOT)"
    echo ""
    
    read -p "Press ENTER when board is ready for flashing, or type 'skip' to skip: " flash_confirm
    
    if [ "$flash_confirm" = "skip" ]; then
        log_warn "Skipping firmware flash. Do this manually later."
        return 0
    fi
    
    # Detect USB device
    USB_DEVICE=$(dmesg | grep -i "stm32" | tail -1 | grep -oE "tty[A-Z0-9]+") || true
    
    if [ -z "$USB_DEVICE" ]; then
        log_warn "Could not auto-detect STM32 device"
        echo "Available serial devices:"
        ls /dev/tty* | grep -E "USB|ACM" || echo "(none found)"
        
        read -p "Enter device name (e.g., ttyUSB0, ttyACM0): " USB_DEVICE
    fi
    
    USB_PATH="/dev/$USB_DEVICE"
    
    if [ ! -e "$USB_PATH" ]; then
        log_error "Device $USB_PATH not found!"
        return 1
    fi
    
    FIRMWARE_BIN="/home/pi/horaltscanner_firmware/firmware/creality_v422/build/firmware.bin"
    
    if [ ! -f "$FIRMWARE_BIN" ]; then
        log_error "Compiled firmware not found at $FIRMWARE_BIN"
        log_error "Make sure compilation succeeded"
        return 1
    fi
    
    log_info "Flashing firmware to $USB_PATH..."
    stm32flash -w "$FIRMWARE_BIN" -v -g 0x08000000 "$USB_PATH" || {
        log_error "Flashing failed!"
        log_error "Try using STM32CubeProgrammer GUI instead"
        return 1
    }
    
    log_success "Firmware flashed successfully!"
}

# 11. Install HoralScanner API
install_horalscanner() {
    log_info "Installing HoralScanner API..."
    
    if [ ! -d "/home/pi/horaltscanner" ]; then
        git clone https://github.com/jose33bro/horaltscanner.git /home/pi/horaltscanner
    fi
    
    # Create venv
    python3 -m venv /home/pi/horaltscanner_env
    source /home/pi/horaltscanner_env/bin/activate
    
    # Install deps
    pip install --upgrade pip setuptools wheel
    pip install -r /home/pi/horaltscanner/requirements.txt
    
    deactivate
    
    log_success "HoralScanner installed"
}

# 12. Install systemd service
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

# 13. Cleanup
cleanup() {
    log_info "Cleaning up old printer config files..."
    
    rm -f /home/pi/printer.cfg
    rm -f /home/pi/printer_data/config/printer.cfg
    
    # Remove old virtual env
    rm -rf /home/pi/.virtualenvs/klippy-env 2>/dev/null || true
    
    log_success "Cleanup complete"
}

# 14. Final summary
summary() {
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║     ✅ Migration Complete: Marlin/Klipper → USB API   ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "📦 What was removed:"
    echo "   ✗ Klipper firmware"
    echo "   ✗ Moonraker daemon"
    echo "   ✗ Mainsail/Fluidd web UI"
    echo "   ✗ Nginx web server"
    echo ""
    echo "📦 What was installed:"
    echo "   ✓ HoralScanner Flask API"
    echo "   ✓ STM32 USB firmware"
    echo "   ✓ Custom web dashboard (port 5000)"
    echo "   ✓ systemd auto-start service"
    echo ""
    echo "🚀 Next steps:"
    echo "   1. Restart Raspberry Pi:"
    echo "      ${BLUE}sudo reboot${NC}"
    echo ""
    echo "   2. After reboot, check status:"
    echo "      ${BLUE}sudo systemctl status horalscanner${NC}"
    echo ""
    echo "   3. Access web dashboard:"
    echo "      ${BLUE}http://$(hostname -I | awk '{print $1}'):5000${NC}"
    echo ""
    echo "📝 Backups saved to:"
    echo "   ${BLUE}$BACKUP_DIR${NC}"
    echo ""
    echo "📚 Documentation:"
    echo "   ${BLUE}https://github.com/jose33bro/horaltscanner${NC}"
    echo ""
}

# Main execution
main() {
    log_warn "This script will REMOVE Klipper/Moonraker and replace with HoralScanner"
    echo ""
    read -p "Continue? (yes/no): " confirm
    
    if [ "$confirm" != "yes" ]; then
        log_warn "Cancelled"
        exit 0
    fi
    
    echo ""
    
    stop_services
    backup_klipper_config
    remove_klipper
    remove_moonraker
    remove_web_ui
    remove_nginx
    install_firmware_tools
    clone_firmware
    compile_firmware
    flash_firmware
    install_horalscanner
    install_service
    cleanup
    
    systemctl daemon-reload
    
    summary
}

main
