#!/bin/bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_DIR="$REPO_ROOT/firmware/creality_v422"
BUILD_VENV="${HORALSCANNER_PLATFORMIO_VENV:-$HOME/.cache/horalscanner-platformio}"
OUTPUT_DIR="$PROJECT_DIR/build"

if [ ! -d "$BUILD_VENV" ]; then
    python3 -m venv "$BUILD_VENV"
fi

"$BUILD_VENV/bin/python" -m pip install --quiet --upgrade pip
"$BUILD_VENV/bin/python" -m pip install --quiet "platformio==6.1.19"
"$BUILD_VENV/bin/python" -m platformio run --project-dir "$PROJECT_DIR"

mkdir -p "$OUTPUT_DIR"
cp "$PROJECT_DIR/.pio/build/creality_v422/firmware.bin" "$OUTPUT_DIR/firmware.bin"
echo "Firmware ready: $OUTPUT_DIR/firmware.bin"
