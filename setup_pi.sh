#!/bin/bash
# HoralScanner — Complete Raspberry Pi 4 Setup & OS Customization
# Usage: bash setup_pi.sh [--full|--update|--install|--repair]

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/home/pi/horaltscanner"
VENV_DIR="/home/pi/horaltscanner_env"
REPO_URL="https://github.com/jose33bro/horaltscanner.git"
BACKUP_DIR="/home/pi/backups"
IMAGE_BUILD_MODE="${HORALSCANNER_IMAGE_BUILD:-0}"
STATE_DIR="/var/lib/horalscanner"
CALIBRATION_FILE="$STATE_DIR/calibration.json"

# Functions
log_info() {
    echo -e "${BLUE}ℹ ${1}${NC}"
}

log_success() {
    echo -e "${GREEN}✓ ${1}${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠ ${1}${NC}"
}

log_error() {
    echo -e "${RED}✗ ${1}${NC}"
}

is_image_build() {
    [ "$IMAGE_BUILD_MODE" = "1" ]
}

# Step 0: Pre-flight checks
preflight_check() {
    log_info "Running preflight checks..."
    
    if [ "$EUID" -ne 0 ]; then
        log_error "Must run with sudo"
        exit 1
    fi
    
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found. Install it first: sudo apt-get install python3 python3-pip"
        exit 1
    fi
    
    if ! command -v git &> /dev/null; then
        log_warn "Git not found. Installing..."
        apt-get update
        apt-get install -y git
    fi
    
    log_success "Preflight checks passed"
}

# Step 0.1: Ensure default Raspberry Pi user exists
ensure_pi_user() {
    if id -u pi >/dev/null 2>&1; then
        return
    fi

    log_warn "User pi not found. Creating default image user..."
    useradd -m -s /bin/bash pi
    echo "pi:raspberry" | chpasswd
    chage -d 0 pi || true
    usermod -aG sudo pi || true
    log_success "User pi created"
}

# Step 1: Update system
update_system() {
    log_info "Updating Raspberry Pi OS..."
    apt-get update
    apt-get upgrade -y
    apt-get autoremove -y
    log_success "System updated"
}

# Step 2: Install system dependencies (Bookworm compatible)
install_system_deps() {
    log_info "Installing system dependencies..."
    
    # Core dependencies
    apt-get install -y \
        build-essential \
        python3-dev \
        python3-pip \
        python3-venv \
        python3-picamera2 \
        git \
        curl \
        wget \
        vim \
        nano \
        htop \
        i2c-tools \
        usbutils \
        libatlas-base-dev \
        libopenblas-dev \
        liblapack-dev \
        libffi-dev \
        libssl-dev \
        libxcb1 \
        libgl1 \
        libglib2.0-0
    
    # Try to install optional packages (may not exist on all systems)
    apt-get install -y libharfbuzz0b || log_warn "libharfbuzz0b not available (optional)"
    apt-get install -y libopenjp2-7 || log_warn "libopenjp2-7 not available (optional)"
    apt-get install -y libopencv-core4.5 || log_warn "libopencv-core not available (optional)"
    apt-get install -y python3-opencv || apt-get install -y python3-cv2 || log_warn "OpenCV Python not available (will install via pip)"
    if apt-cache show rpicam-apps >/dev/null 2>&1; then
        apt-get install -y rpicam-apps
    else
        apt-get install -y libcamera-apps
    fi
    
    log_success "System dependencies installed"
}

# Step 3: Configure GPIO access
configure_gpio() {
    log_info "Configuring GPIO access..."
    
    for group in gpio dialout video render i2c spi; do
        getent group "$group" >/dev/null && usermod -a -G "$group" pi || true
    done
    
    # Enable I2C and SPI in boot config
    if [ -f /boot/firmware/config.txt ]; then
        sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' /boot/firmware/config.txt || true
        sed -i 's/^#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt || true
        sed -i 's/^#enable_uart=1/enable_uart=1/' /boot/firmware/config.txt || true
        
        # GPIO18 drives the red LED channel and must not be claimed by gpio-ir.
        sed -i '/^[[:space:]]*dtoverlay=gpio-ir/d' /boot/firmware/config.txt || true
    else
        log_warn "Boot config not found at /boot/firmware/config.txt"
    fi
    
    log_success "GPIO configured"
}

configure_persistent_state() {
    log_info "Ensuring persistent runtime calibration storage..."
    install -d -o pi -g pi -m 0750 "$STATE_DIR"
    if [ -e "$CALIBRATION_FILE" ]; then
        chown pi:pi "$CALIBRATION_FILE"
        chmod 0640 "$CALIBRATION_FILE"
        log_info "Preserved measured calibration at $CALIBRATION_FILE"
    fi
}

# Step 4: Clone repository
clone_repo() {
    log_info "Cloning HoralScanner repository..."

    if [ -n "${HORALSCANNER_SOURCE_DIR:-}" ] && [ -d "${HORALSCANNER_SOURCE_DIR}" ]; then
        rm -rf "$INSTALL_DIR"
        mkdir -p "$(dirname "$INSTALL_DIR")"
        cp -a "${HORALSCANNER_SOURCE_DIR}" "$INSTALL_DIR"
        rm -rf "$INSTALL_DIR/.git"
        cd "$INSTALL_DIR"
        log_success "Repository copied from local source"
        return
    fi
    
    if [ -d "$INSTALL_DIR" ]; then
        log_warn "Directory $INSTALL_DIR already exists. Updating..."
        cd "$INSTALL_DIR"
        git pull origin main || log_warn "Could not pull updates"
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone "$REPO_URL" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
    
    log_success "Repository ready"
}

configure_serial_devices() {
    if is_image_build; then
        return
    fi

    if [ -f /etc/udev/rules.d/99-horalscanner-serial.rules ]; then
        udevadm control --reload-rules
        udevadm trigger --subsystem-match=tty
        udevadm settle
    fi

    mapfile -t serial_devices < <(
        find /dev -maxdepth 1 \( -name 'ttyUSB*' -o -name 'ttyACM*' \) -print
    )
    if [ "${#serial_devices[@]}" -ge 2 ]; then
        log_info "Creating stable Creality and TF-Luna device aliases..."
        bash "$INSTALL_DIR/software/scripts/configure_serial_devices.sh" ||
            log_warn "Serial aliases could not be configured automatically"
    else
        log_warn "Connect Creality and TF-Luna, then run software/scripts/configure_serial_devices.sh"
    fi
}

# Step 5: Create virtual environment and install Python deps
setup_python() {
    log_info "Setting up Python virtual environment..."

    if [ -x "$VENV_DIR/bin/python3" ] &&
       ! "$VENV_DIR/bin/python3" -c "import sys" >/dev/null 2>&1; then
        log_warn "Existing virtual environment is broken; recreating it..."
        rm -rf "$VENV_DIR"
    fi
    if [ ! -x "$VENV_DIR/bin/python3" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv --system-site-packages "$VENV_DIR"
    fi

    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip setuptools wheel
    
    # Install requirements with fallback
    log_info "Installing Python dependencies (this may take ~15 minutes)..."
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        pip install -r "$INSTALL_DIR/requirements.txt" || log_warn "Some packages failed to install"
    else
        log_warn "requirements.txt not found, installing basic packages..."
        pip install flask flask-cors pillow numpy requests pyserial
    fi

    if [ "$(uname -m)" = "aarch64" ]; then
        log_info "Open3D ARM64 installer available at software/scripts/install_open3d_pi.sh"
        log_info "Run it after setup to enable Poisson mesh reconstruction"
    fi
    
    deactivate
    
    log_success "Python environment ready"
}

# Step 6: Install systemd service
install_service() {
    log_info "Installing systemd service..."
    
    # Determine API script location
    API_SCRIPT="$INSTALL_DIR/software/api/horalscanner_api.py"
    if [ ! -f "$API_SCRIPT" ]; then
        API_SCRIPT="$INSTALL_DIR/horalscanner_api.py"
    fi
    
    cat > /etc/systemd/system/horalscanner.service <<EOF
[Unit]
Description=HoralScanner 3D Scanner API
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$VENV_DIR/bin"
Environment="PYTHONPATH=$INSTALL_DIR"
Environment="HORALSCANNER_CALIBRATION_STATE=$CALIBRATION_FILE"
StateDirectory=horalscanner
StateDirectoryMode=0750
ExecStart=$VENV_DIR/bin/python3 $API_SCRIPT
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=horalscanner

[Install]
WantedBy=multi-user.target
EOF

    if is_image_build; then
        mkdir -p /etc/systemd/system/multi-user.target.wants
        ln -sf /etc/systemd/system/horalscanner.service /etc/systemd/system/multi-user.target.wants/horalscanner.service
    else
        systemctl daemon-reload
        systemctl enable horalscanner
    fi
    
    log_success "Service installed and enabled"
}

# Step 7: Backup system
backup_system() {
    log_info "Creating system backup..."
    
    mkdir -p "$BACKUP_DIR"
    STAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/horaltscanner_backup_${STAMP}.tar.gz"
    
    tar -czf "$BACKUP_FILE" \
        -C "$INSTALL_DIR" \
        --exclude='.git' \
        --exclude='backups' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        . 2>/dev/null || true
    
    log_success "Backup created: $BACKUP_FILE"
}

# Step 8: Test installation
test_installation() {
    log_info "Testing installation..."
    
    source "$VENV_DIR/bin/activate"
    
    python3 -c "import flask, cv2, serial, PIL, numpy; print('✓ Core Python imports')" \
        || { log_error "Required Python import check failed"; deactivate; return 1; }
    python3 -c "from picamera2 import Picamera2; print('✓ Picamera2')" \
        || { log_error "Picamera2 import check failed"; deactivate; return 1; }
    if ! command -v rpicam-still >/dev/null 2>&1 &&
       ! command -v libcamera-still >/dev/null 2>&1; then
        log_error "Neither rpicam-still nor libcamera-still is installed"
        deactivate
        return 1
    fi
    
    deactivate
    
    log_success "Installation tests complete"
}

non_motion_health_check() {
    log_info "Running non-motion health checks..."
    test -d "$STATE_DIR" || {
        log_error "Persistent state directory is missing"
        return 1
    }
    systemctl is-enabled --quiet horalscanner || {
        log_error "HoralScanner service is not enabled"
        return 1
    }
    if systemctl is-active --quiet horalscanner; then
        curl --fail --silent --max-time 5 http://127.0.0.1:5000/api/status >/dev/null \
            || { log_error "Service /api/status is not responding"; return 1; }
    else
        log_error "Service is not active; inspect journalctl -u horalscanner"
        return 1
    fi
    for alias in /dev/horalscanner_mcu /dev/horalscanner_lidar; do
        [ -e "$alias" ] || log_warn "Stable serial alias is not currently present: $alias"
    done
    log_success "Health checks complete; no motors or lasers were activated"
}

# Step 9: Quick start
quick_start() {
    if is_image_build; then
        log_success "HoralScanner configured in image and ready for first boot"
        return
    fi

    log_info "Starting HoralScanner service..."
    
    systemctl start horalscanner
    sleep 3
    
    if systemctl is-active --quiet horalscanner; then
        log_success "HoralScanner is running!"
        echo ""
        echo -e "${GREEN}═══════════════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}✓ HoralScanner Installation Complete!${NC}"
        echo -e "${GREEN}═══════════════════════════════════════════════════════╗${NC}"
        echo ""
        echo -e "📊 Access the dashboard:"
        echo -e "   ${BLUE}http://<your-pi-ip>:5000${NC}"
        echo ""
        echo -e "📝 View logs:"
        echo -e "   ${BLUE}sudo journalctl -u horalscanner -f${NC}"
        echo ""
        echo -e "🔧 Service commands:"
        echo -e "   Start:   ${BLUE}sudo systemctl start horalscanner${NC}"
        echo -e "   Stop:    ${BLUE}sudo systemctl stop horalscanner${NC}"
        echo -e "   Status:  ${BLUE}sudo systemctl status horalscanner${NC}"
        echo -e "   Restart: ${BLUE}sudo systemctl restart horalscanner${NC}"
        echo ""
    else
        log_error "Service failed to start. Check logs:"
        journalctl -u horalscanner -n 20
    fi
}

# Main execution
main() {
    MODE="${1:-}"
    if [ -z "$MODE" ]; then
        MODE="--full"
    fi
    
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║       HoralScanner — Raspberry Pi 4 Setup Script          ║"
    echo "║                     Version 1.0.0                         ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo ""
    
    case "$MODE" in
        --full)
            log_info "Running FULL setup (system + code + service)"
            preflight_check
            ensure_pi_user
            update_system
            install_system_deps
            configure_gpio
            clone_repo
            configure_persistent_state
            configure_serial_devices
            setup_python
            install_service
            backup_system
            test_installation
            quick_start
            ;;
        --update)
            log_info "Running UPDATE ONLY"
            cd "$INSTALL_DIR"
            git pull origin main
            configure_persistent_state
            configure_serial_devices
            setup_python
            install_service
            systemctl restart horalscanner
            non_motion_health_check
            log_success "Update complete"
            ;;
        --install)
            log_info "Running INSTALL ONLY (no system updates)"
            preflight_check
            ensure_pi_user
            install_system_deps
            configure_gpio
            clone_repo
            configure_persistent_state
            configure_serial_devices
            setup_python
            install_service
            quick_start
            ;;
        --repair)
            log_info "Running POST-OS-UPGRADE REPAIR; measured calibration is preserved"
            preflight_check
            ensure_pi_user
            update_system
            install_system_deps
            configure_gpio
            if [ ! -d "$INSTALL_DIR/.git" ]; then
                clone_repo
            fi
            configure_persistent_state
            configure_serial_devices
            setup_python
            install_service
            systemctl restart horalscanner
            test_installation
            non_motion_health_check
            log_success "Post-upgrade repair complete"
            ;;
        --quick-test)
            log_info "Running quick test"
            test_installation
            ;;
        *)
            log_error "Unknown option: $MODE"
            echo ""
            echo "Usage: sudo bash setup_pi.sh [OPTION]"
            echo ""
            echo "Options:"
            echo "  --full          Full setup (system + code + service) [DEFAULT]"
            echo "  --install       Install only (skip system updates)"
            echo "  --update        Update code and restart service"
            echo "  --repair        Repair dependencies/services after an OS upgrade"
            echo "  --quick-test    Test Python imports only"
            echo ""
            exit 1
            ;;
    esac
    
    echo ""
}

# Run
main "$@"
