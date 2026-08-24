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

# Step 2: Install system dependencies
install_system_deps() {
    log_info "Installing system dependencies..."
    
    apt-get install -y \
        build-essential \
        python3-dev \
        python3-pip \
        python3-venv \
        libatlas-base-dev \
        libjasper-dev \
        libharfbuzz0b \
        libwebp6 \
        libtiff5 \
        libopenjp2-7 \
        libjasper1 \
        libopenblas-dev \
        liblapack-dev \
        libxcb1 \
        libffi-dev \
        libssl-dev \
        libopencv-dev \
        python3-opencv \
        git \
        curl \
        wget \
        vim \
        nano \
        htop \
        i2c-tools \
        usbutils
    
    log_success "System dependencies installed"
}

# Step 3: Configure GPIO access
configure_gpio() {
    log_info "Configuring GPIO access..."
    
    # Add pi user to gpio group
    usermod -a -G gpio pi || true
    
    # Enable I2C and SPI
    sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' /boot/firmware/config.txt || true
    sed -i 's/^#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt || true
    
    # Enable UART for serial communication
    sed -i 's/^#enable_uart=1/enable_uart=1/' /boot/firmware/config.txt || true
    
    log_success "GPIO configured"
}

# Step 4: Clone repository
clone_repo() {
    log_info "Cloning HoralScanner repository..."
    
    if [ -d "$INSTALL_DIR" ]; then
        log_warn "Directory $INSTALL_DIR already exists. Skipping clone..."
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    
    cd "$INSTALL_DIR"
    git pull origin main
    
    log_success "Repository ready"
}

# Step 5: Create virtual environment and install Python deps
setup_python() {
    log_info "Setting up Python virtual environment..."
    
    # Create venv
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip setuptools wheel
    
    # Install requirements
    log_info "Installing Python dependencies (this may take ~15 minutes)..."
    pip install -r "$INSTALL_DIR/requirements.txt"
    
    deactivate
    
    log_success "Python environment ready"
}

# Step 6: Install systemd service
install_service() {
    log_info "Installing systemd service..."
    
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
ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/software/api/horalscanner_api.py
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

# Step 7: Backup and update
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
    python3 -c "import flask; print('Flask OK')" || log_warn "Flask import failed"
    python3 -c "import cv2; print('OpenCV OK')" || log_warn "OpenCV import failed"
    python3 -c "import gpiozero; print('gpiozero OK')" || log_warn "gpiozero import failed"
    python3 -c "import serial; print('pyserial OK')" || log_warn "pyserial import failed"
    
    deactivate
    
    log_success "Installation tests complete"
}

# Step 9: Quick start
quick_start() {
    log_info "Starting HoralScanner service..."
    
    systemctl start horalscanner
    sleep 2
    
    if systemctl is-active --quiet horalscanner; then
        log_success "HoralScanner is running!"
        echo ""
        echo -e "${GREEN}═══════════════════════════════════════${NC}"
        echo -e "${GREEN}HoralScanner Installation Complete!${NC}"
        echo -e "${GREEN}═══════════════════════════════════════${NC}"
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
        echo ""
    else
        log_error "Service failed to start. Check logs:"
        journalctl -u horalscanner -n 20
    fi
}

# Step 10: Custom OS image creation helper
create_os_image() {
    log_info "Creating instructions for OS image..."
    
    cat > "$INSTALL_DIR/CREATE_CUSTOM_OS.md" <<'EOF'
# Creating a Custom HoralScanner OS Image

## Option A: Using Raspberry Pi Imager (Recommended)

1. **Download Raspberry Pi Imager**
   - https://www.raspberrypi.com/software/

2. **Prepare SD card**
   - Insert SD card
   - Open Imager
   - OS: Choose "Raspberry Pi OS (Bookworm)" - 64-bit Lite
   - Storage: Select your SD card
   - Settings (gear icon):
     - Set hostname: `horaltscanner`
     - Enable SSH (password auth)
     - Set username: `pi`, password: your choice
     - Configure WiFi (if needed)
     - Set locale & timezone

3. **Write and boot**

4. **Run setup script**
   ```bash
   ssh pi@horaltscanner.local
   sudo bash -c "curl -sSL https://raw.githubusercontent.com/jose33bro/horaltscanner/main/setup_pi.sh | bash"
   ```

## Option B: Manual Custom Image Creation

### Prerequisites
- Host machine (Linux/Mac)
- `rpi-imager` or manual `dd`
- PiShrink or similar for image compression

### Step-by-step

1. **Create base image**
   ```bash
   # Flash base Raspberry Pi OS to SD
   rpi-imager --cli \
     --os "raspberry_pi_os_lite" \
     --output /path/to/horaltscanner.img \
     --storage /dev/sdX
   ```

2. **Mount and customize**
   ```bash
   # Mount rootfs
   mkdir -p /mnt/rpi
   sudo mount /dev/mapper/rootfs /mnt/rpi
   
   # Chroot into image
   sudo chroot /mnt/rpi /bin/bash
   
   # Inside chroot:
   apt-get update
   apt-get upgrade -y
   
   # Copy HoralScanner repo
   git clone https://github.com/jose33bro/horaltscanner.git /home/pi/horaltscanner
   
   # Run setup
   bash /home/pi/horaltscanner/setup_pi.sh --install-only
   
   # Clean up
   apt-get clean
   apt-get autoremove -y
   rm -rf /tmp/*
   
   exit
   ```

3. **Unmount and shrink**
   ```bash
   sudo umount /mnt/rpi
   pishrink.sh horaltscanner.img horaltscanner_slim.img
   ```

4. **Flash to multiple cards**
   ```bash
   dd if=horaltscanner_slim.img of=/dev/sdX bs=4M status=progress
   ```

## Option C: Using GitHub Actions (Future)

Create `.github/workflows/build-image.yml`:
- Use `Pi-Gen` builder
- Customize stage3 with HoralScanner setup
- Produce `.img` artifact

EOF

    log_success "OS image creation guide created at: $INSTALL_DIR/CREATE_CUSTOM_OS.md"
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
            create_os_image
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
            create_os_image
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
