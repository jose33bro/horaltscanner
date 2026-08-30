#!/bin/bash

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_PATH="${HORALSCANNER_HARDWARE_CONFIG:-$REPO_ROOT/config/horalscanner_config.json}"
RULES_PATH="/etc/udev/rules.d/99-horalscanner-serial.rules"

service_was_active=false
if systemctl is-active --quiet horalscanner 2>/dev/null; then
    service_was_active=true
    systemctl stop horalscanner
fi

restore_service() {
    if [ "$service_was_active" = true ]; then
        systemctl start horalscanner || true
    fi
}
trap restore_service EXIT

mapfile -t devices < <(
    find /dev -maxdepth 1 \( -name 'ttyUSB*' -o -name 'ttyACM*' \) -print | sort
)

if [ "${#devices[@]}" -lt 2 ]; then
    echo "Two serial devices are required (Creality and TF-Luna)." >&2
    exit 1
fi

lidar=""
for device in "${devices[@]}"; do
    stty -F "$device" 115200 raw -echo 2>/dev/null || continue
    sample="$( (timeout 2 od -An -tx1 -N 36 "$device" 2>/dev/null || true) | tr -d ' \n')"
    if [[ "$sample" == *5959* ]]; then
        if [ -n "$lidar" ]; then
            echo "More than one TF-Luna stream was detected." >&2
            exit 1
        fi
        lidar="$device"
    fi
done

if [ -z "$lidar" ]; then
    echo "No TF-Luna frame (59 59) was detected." >&2
    exit 1
fi

mcu=""
for device in "${devices[@]}"; do
    if [ "$device" != "$lidar" ]; then
        mcu="$device"
        break
    fi
done

property() {
    udevadm info --query=property --name="$1" |
        sed -n "s/^$2=//p" |
        head -n 1
}

mcu_path="$(property "$mcu" ID_PATH)"
lidar_path="$(property "$lidar" ID_PATH)"
if [ -z "$mcu_path" ] || [ -z "$lidar_path" ] || [ "$mcu_path" = "$lidar_path" ]; then
    echo "Unable to determine two unique physical USB paths." >&2
    exit 1
fi

case "$mcu_path$lidar_path" in
    *[!A-Za-z0-9._:/-]*)
        echo "Unexpected characters in USB physical path." >&2
        exit 1
        ;;
esac

cat >"$RULES_PATH" <<EOF
SUBSYSTEM=="tty", ENV{ID_PATH}=="$mcu_path", SYMLINK+="horalscanner_mcu", GROUP="dialout", MODE="0660"
SUBSYSTEM=="tty", ENV{ID_PATH}=="$lidar_path", SYMLINK+="horalscanner_lidar", GROUP="dialout", MODE="0660"
EOF

udevadm control --reload-rules
udevadm trigger --subsystem-match=tty
udevadm settle

python3 - "$CONFIG_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as config_file:
    config = json.load(config_file)
config["serial"]["mcu_port"] = "/dev/horalscanner_mcu"
config["serial"]["lidar_port"] = "/dev/horalscanner_lidar"
with open(path, "w", encoding="utf-8") as config_file:
    json.dump(config, config_file, indent=2)
    config_file.write("\n")
PY

echo "Creality: $mcu -> /dev/horalscanner_mcu"
echo "TF-Luna:  $lidar -> /dev/horalscanner_lidar"
