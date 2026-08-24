#!/bin/bash
# HoralScanner — Clean OS Image Builder
# Creates a pre-configured Raspberry Pi OS image with ONLY HoralScanner (no Klipper)

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
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   HoralScanner Clean OS Image Builder                   ║"
echo "║   Creates pre-configured Raspberry Pi OS with            ║"
echo "║   ONLY HoralScanner (no Klipper/Marlin)                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

if [ "$EUID" -ne 0 ]; then
    log_error "Must run with sudo"
    exit 1
fi

# Configuration
WORK_DIR=$(pwd)
BUILD_DIR="${WORK_DIR}/horaltscanner-os-build"
MOUNT_DIR="${BUILD_DIR}/mnt"
OS_IMAGE="${BUILD_DIR}/horaltscanner-bookworm-lite.img"
OS_IMAGE_COMPRESSED="${BUILD_DIR}/horaltscanner-bookworm-lite.img.xz"

# Step 1: Check requirements
check_requirements() {
    log_info "Checking requirements..."
    
    # Check for necessary tools
    command -v wget >/dev/null 2>&1 || { apt-get install -y wget; }
    command -v xz >/dev/null 2>&1 || { apt-get install -y xz-utils; }
    command -v losetup >/dev/null 2>&1 || { apt-get install -y util-linux; }
    command -v parted >/dev/null 2>&1 || { apt-get install -y parted; }
    command -v qemu-arm-static >/dev/null 2>&1 || { apt-get install -y qemu-user-static; }
    
    log_success "Requirements OK"
}

# Step 2: Create build directory
prepare_build() {
    log_info "Preparing build environment..."
    mkdir -p "$BUILD_DIR"
    mkdir -p "$MOUNT_DIR"
    cd "$BUILD_DIR"
    log_success "Build directory ready: $BUILD_DIR"
}

# Step 3: Download base image
download_base_image() {
    log_info "Downloading Raspberry Pi OS Bookworm 64-bit Lite..."
    
    # Latest Bookworm image
    IMAGE_URL="https://downloads.raspberrypi.org/raspios_arm64/images/raspios_arm64-2024-03-12/2024-03-12-raspios-bookworm-arm64-lite.img.xz"
    BASE_IMAGE="${BUILD_DIR}/base-bookworm.img.xz"
    BASE_IMAGE_EXTRACTED="${BUILD_DIR}/base-bookworm.img"
    
    if [ ! -f "$BASE_IMAGE" ]; then
        log_info "Downloading (this may take 5-10 minutes)..."
        wget -q --show-progress "$IMAGE_URL" -O "$BASE_IMAGE"
    else
        log_warn "Base image already exists, skipping download"
    fi
    
    # Extract
    if [ ! -f "$BASE_IMAGE_EXTRACTED" ]; then
        log_info "Extracting base image..."
        xz -d -k "$BASE_IMAGE" -c > "$BASE_IMAGE_EXTRACTED"
    fi
    
    # Copy to working image
    cp "$BASE_IMAGE_EXTRACTED" "$OS_IMAGE"
    
    log_success "Base image ready"
}

# Step 4: Expand image
expand_image() {
    log_info "Expanding image size (+2GB for software)..."
    
    # Add 2GB
    dd if=/dev/zero bs=1M count=2048 >> "$OS_IMAGE"
    
    log_success "Image expanded"
}

# Step 5: Mount image
mount_image() {
    log_info "Mounting image..."
    
    # Setup loop device
    LOOP_DEV=$(losetup -f)
    losetup "$LOOP_DEV" "$OS_IMAGE"
    
    partprobe "$LOOP_DEV" 2>/dev/null || true
    sleep 1
    
    # Mount partitions
    mount "${LOOP_DEV}p1" "${MOUNT_DIR}/boot" 2>/dev/null || mount "${LOOP_DEV}p1" "${MOUNT_DIR}/boot"
    mount "${LOOP_DEV}p2" "${MOUNT_DIR}/root" 2>/dev/null || mount "${LOOP_DEV}p2" "${MOUNT_DIR}/root"
    
    # Copy QEMU for ARM execution
    mkdir -p "${MOUNT_DIR}/root/usr/bin"
    cp /usr/bin/qemu-arm-static "${MOUNT_DIR}/root/usr/bin/" || true
    
    log_success "Image mounted at $MOUNT_DIR"
}

# Step 6: Customize in chroot
customize_image() {
    log_info "Customizing image (this takes ~15 minutes)..."
    
    # Mount pseudo-filesystems
    mount -t proc proc "${MOUNT_DIR}/root/proc"
    mount -t sysfs sys "${MOUNT_DIR}/root/sys"
    mount -o bind /dev "${MOUNT_DIR}/root/dev"
    mount -o bind /dev/pts "${MOUNT_DIR}/root/dev/pts"
    mount -o bind /run "${MOUNT_DIR}/root/run"
    
    # Run customization inside chroot
    chroot "${MOUNT_DIR}/root" /bin/bash << 'CHROOT_SCRIPT'
set -e

export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8

# Update
apt-get update
apt-get upgrade -y

# Remove old packages
apt-get remove -y nginx lighttpd apache2 2>/dev/null || true
apt-get autoremove -y

# Install essential packages
apt-get install -y \
    python3 python3-pip python3-venv \
    python3-dev build-essential \
    git curl wget nano vim \
    libopencv-dev python3-opencv \
    libatlas-base-dev libjasper-dev \
    libharfbuzz0b libwebp6 libtiff5 libopenjp2-7 \
    libopenblas-dev liblapack-dev \
    i2c-tools usbutils \
    systemd systemd-sysv

# Add user to gpio group
usermod -a -G gpio pi || true
usermod -a -G dialout pi || true

# Clone HoralScanner
git clone https://github.com/jose33bro/horaltscanner.git /home/pi/horaltscanner
cd /home/pi/horaltscanner

# Setup Python environment
python3 -m venv /home/pi/horaltscanner_env
source /home/pi/horaltscanner_env/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
deactivate

# Fix ownership
chown -R pi:pi /home/pi/horaltscanner
chown -R pi:pi /home/pi/horaltscanner_env

# Install systemd service
cat > /etc/systemd/system/horalscanner.service <<'SERVICE'
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
SERVICE

systemctl enable horalscanner

# Configure GPIO access
sed -i 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' /boot/firmware/config.txt || true
sed -i 's/^#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt || true
sed -i 's/^#enable_uart=1/enable_uart=1/' /boot/firmware/config.txt || true

# Cleanup
apt-get clean
apt-get autoremove -y
rm -rf /tmp/*
rm -rf /var/lib/apt/lists/*
rm -rf /home/pi/.cache

CHROOT_SCRIPT

    log_success "Customization complete"
}

# Step 7: Unmount image
unmount_image() {
    log_info "Unmounting image..."
    
    umount "${MOUNT_DIR}/root/proc" 2>/dev/null || true
    umount "${MOUNT_DIR}/root/sys" 2>/dev/null || true
    umount "${MOUNT_DIR}/root/dev/pts" 2>/dev/null || true
    umount "${MOUNT_DIR}/root/dev" 2>/dev/null || true
    umount "${MOUNT_DIR}/root/run" 2>/dev/null || true
    
    sleep 1
    
    umount "${MOUNT_DIR}/boot" 2>/dev/null || true
    umount "${MOUNT_DIR}/root" 2>/dev/null || true
    
    losetup -d "$LOOP_DEV" 2>/dev/null || true
    
    log_success "Image unmounted"
}

# Step 8: Compress image
compress_image() {
    log_info "Compressing image (this takes 10-20 minutes)..."
    
    xz -v --threads=4 -k "$OS_IMAGE"
    
    SIZE_ORIG=$(du -h "$OS_IMAGE" | cut -f1)
    SIZE_COMP=$(du -h "$OS_IMAGE_COMPRESSED" | cut -f1)
    
    log_success "Image compressed: $SIZE_ORIG → $SIZE_COMP"
}

# Step 9: Create README
create_readme() {
    log_info "Creating image documentation..."
    
    cat > "${BUILD_DIR}/README_IMAGE.txt" <<'EOF'
╔════════════════════════════════════════════════════════════╗
║        HoralScanner Clean OS Image                        ║
║        Raspberry Pi 4 64-bit Bookworm                     ║
╚════════════════════════════════════════════════════════════╝

CONTENTS:
=========
- Raspberry Pi OS Bookworm 64-bit (latest)
- HoralScanner Flask API (port 5000)
- Python 3.9+ with all dependencies
- systemd service (auto-starts on boot)
- GPIO, I2C, SPI, UART enabled
- NO Klipper, NO Marlin, NO Moonraker
- NO Mainsail/Fluidd, NO Nginx

QUICK START:
============

1. Flash to SD card (2GB+ recommended):
   On Linux/Mac:
     xzcat horaltscanner-bookworm-lite.img.xz | dd of=/dev/sdX bs=4M status=progress sync
   
   On Windows:
     Use Raspberry Pi Imager or Balena Etcher with the .img.xz file

2. Insert SD card into Pi 4 and boot

3. SSH into Pi:
   ssh pi@raspberrypi.local
   (password: raspberry - CHANGE THIS!)

4. Access web dashboard:
   http://raspberrypi.local:5000
   (or http://<your-pi-ip>:5000)

5. Verify service:
   sudo systemctl status horalscanner

CONFIGURATION:
===============

Change password:
  passwd

Change hostname:
  sudo raspi-config → System Options → Hostname

Enable WiFi:
  sudo raspi-config → System Options → Wireless LAN

Expand filesystem:
  sudo raspi-config → Advanced Options → Expand Filesystem

HARDWARE SETUP:
================

Wire your hardware according to:
  https://github.com/jose33bro/horaltscanner/blob/main/hardware/wiring_diagram.md

GPIO Pins (Raspberry Pi):
  GPIO27  → Laser Left
  GPIO22  → Laser Right
  GPIO18  → LED Red
  GPIO13  → LED Green
  GPIO19  → LED Blue
  GPIO23  → Pi Fan

Creality V4.2.2 (via USB):
  PC2/PB9/PC3  → Stepper X
  PB8/PB7/PC3  → Stepper Y
  PB6/PB5/PC3  → Stepper Z
  PA0          → Creality Fan
  PA8          → Temperature Fan
  PC5          → Board Temperature

TROUBLESHOOTING:
=================

Check service status:
  sudo systemctl status horalscanner

View logs:
  sudo journalctl -u horalscanner -f

Restart service:
  sudo systemctl restart horalscanner

Test API:
  curl http://localhost:5000/api/status

DOCUMENTATION:
================

Main repo: https://github.com/jose33bro/horaltscanner
Quick start: https://github.com/jose33bro/horaltscanner/blob/main/QUICK_START.md
API docs: https://github.com/jose33bro/horaltscanner/blob/main/USAGE.md

SECURITY NOTES:
================

⚠️ Default credentials:
   User: pi
   Password: raspberry

You MUST change the password immediately!
   passwd

For remote access, set up:
  - SSH key authentication (disable password)
  - Firewall (ufw)
  - VPN

This system is designed for LOCAL LAN use only.

BUILD INFO:
============

Image built: $(date)
Base: Raspberry Pi OS Bookworm 64-bit Lite
Size: ~2GB compressed, ~10GB uncompressed
HoralScanner version: 1.0.0

EOF

    log_success "Documentation created"
}

# Main execution
main() {
    check_requirements
    prepare_build
    download_base_image
    expand_image
    mount_image
    customize_image
    unmount_image
    compress_image
    create_readme
    
    echo ""
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║    🎉 OS Image Build Complete!                       ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo ""
    echo "📦 Output location:"
    echo "   ${BLUE}${BUILD_DIR}${NC}"
    echo ""
    echo "📁 Files created:"
    echo "   • ${GREEN}horaltscanner-bookworm-lite.img.xz${NC} (compressed, ready to flash)"
    echo "   • horaltscanner-bookworm-lite.img (uncompressed)"
    echo "   • README_IMAGE.txt (flashing instructions)"
    echo ""
    echo "💾 Image size:"
    echo "   Compressed: $(du -h "$OS_IMAGE_COMPRESSED" | cut -f1)"
    echo "   Uncompressed: $(du -h "$OS_IMAGE" | cut -f1)"
    echo ""
    echo "🚀 Next steps:"
    echo ""
    echo "1. Flash to SD card:"
    echo "   ${BLUE}xzcat ${OS_IMAGE_COMPRESSED} | dd of=/dev/sdX bs=4M status=progress sync${NC}"
    echo ""
    echo "2. Insert SD into Pi 4"
    echo ""
    echo "3. SSH and configure:"
    echo "   ${BLUE}ssh pi@raspberrypi.local${NC}"
    echo "   ${BLUE}passwd${NC}  (change password)"
    echo ""
    echo "4. Access dashboard:"
    echo "   ${BLUE}http://raspberrypi.local:5000${NC}"
    echo ""
}

main
