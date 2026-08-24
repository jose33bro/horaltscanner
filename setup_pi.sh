#!/bin/bash
# HoralScanner — Complete Raspberry Pi 4 Setup & OS Customization
# Usage: bash setup_pi.sh [--full|--update|--install]

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
        libxcb1
    
    # Try to install optional packages (may not exist on all systems)
    apt-get install -y libharfbuzz0b || log_warn "libharfbuzz0b not available (optional)"
    apt-get install -y libopenjp2-7 || log_warn "libopenjp2-7 not available (optional)"
    apt-get install -y libopencv-core4.5 || log_warn "libopencv-core not available (optional)"
    apt-get install -y python3-opencv || apt-get install -y python3-cv2 || log_warn "OpenCV Python not available (will install via pip)"
    
    log_success "System dependencies installed"
}

# Step 3: Configure GPIO access
configure_gpio() {
    log_info "Configuring GPIO access..."
    
    # Add pi user to gpio group
    usermod -a -G gpio pi || true
    usermod -a -G dialout pi || true
    
    # Enable I2C and SPI in boot config
    if [ -f /boot/firmware/config.txt ]; then
        sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' /boot/firmware/config.txt || true
        sed -i 's/^#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt || true
        sed -i 's/^#enable_uart=1/enable_uart=1/' /boot/firmware/config.txt || true
        
        # Ensure dtoverlay is enabled
        grep -q "dtoverlay=gpio-ir" /boot/firmware/config.txt || echo "dtoverlay=gpio-ir" >> /boot/firmware/config.txt || true
    else
        log_warn "Boot config not found at /boot/firmware/config.txt"
    fi
    
    log_success "GPIO configured"
}

# Step 4: Clone repository
clone_repo() {
    log_info "Cloning HoralScanner repository..."
    
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

# Step 5: Create virtual environment and install Python deps
setup_python() {
    log_info "Setting up Python virtual environment..."
    
    # Remove old venv if exists
    if [ -d "$VENV_DIR" ]; then
        log_warn "Removing old venv..."
        rm -rf "$VENV_DIR"
    fi
    
    # Create venv
    python3 -m venv "$VENV_DIR"
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
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/python3 $API_SCRIPT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=horalscanner

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable horalscanner
    
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
    
    # Test imports
    python3 -c "import flask; print('✓ Flask')" 2>/dev/null || log_warn "Flask import failed"
    python3 -c "import cv2; print('✓ OpenCV')" 2>/dev/null || log_warn "OpenCV import failed (optional)"
    python3 -c "import serial; print('✓ pyserial')" 2>/dev/null || log_warn "pyserial import failed"
    python3 -c "import PIL; print('✓ Pillow')" 2>/dev/null || log_warn "Pillow import failed"
    
    deactivate
    
    log_success "Installation tests complete"
}

# Step 9: Quick start
quick_start() {
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
    MODE="${1:-full}"
    
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
            update_system
            install_system_deps
            configure_gpio
            clone_repo
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
            source "$VENV_DIR/bin/activate"
            pip install -r requirements.txt --upgrade
            deactivate
            systemctl restart horalscanner
            log_success "Update complete"
            ;;
        --install)
            log_info "Running INSTALL ONLY (no system updates)"
            preflight_check
            install_system_deps
            configure_gpio
            clone_repo
            setup_python
            install_service
            quick_start
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
            echo "  --quick-test    Test Python imports only"
            echo ""
            exit 1
            ;;
    esac
    
    echo ""
}

# Run
main "$@"
