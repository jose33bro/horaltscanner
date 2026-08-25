#!/bin/bash
# Build the official headless Open3D Python package for Raspberry Pi OS ARM64.

set -euo pipefail

OPEN3D_VERSION="${OPEN3D_VERSION:-0.19.0}"
OPEN3D_BUILD_JOBS="${OPEN3D_BUILD_JOBS:-2}"
CACHE_DIR="${OPEN3D_CACHE_DIR:-$HOME/.cache/horalscanner}"
SOURCE_DIR="$CACHE_DIR/Open3D-$OPEN3D_VERSION"
PYTHON_BIN="${OPEN3D_PYTHON:-/home/pi/horaltscanner_env/bin/python3}"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    "$PYTHON_BIN" -m pip install "open3d==$OPEN3D_VERSION"
    "$PYTHON_BIN" -c "import open3d; print('Open3D', open3d.__version__)"
    exit 0
fi

if "$PYTHON_BIN" -c "import open3d" >/dev/null 2>&1; then
    "$PYTHON_BIN" -c "import open3d; print('Open3D already installed:', open3d.__version__)"
    exit 0
fi

sudo apt-get update
sudo apt-get install -y \
    build-essential \
    cmake \
    git \
    libblas-dev \
    liblapack-dev \
    liblapacke-dev \
    libopenblas-dev \
    python3-dev

mkdir -p "$CACHE_DIR"
if [ ! -d "$SOURCE_DIR/.git" ]; then
    git clone --depth 1 --branch "v$OPEN3D_VERSION" \
        https://github.com/isl-org/Open3D.git "$SOURCE_DIR"
fi

cmake -S "$SOURCE_DIR" -B "$SOURCE_DIR/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_CUDA_MODULE=OFF \
    -DBUILD_GUI=OFF \
    -DBUILD_ISPC_MODULE=OFF \
    -DBUILD_JUPYTER_EXTENSION=OFF \
    -DBUILD_PYTORCH_OPS=OFF \
    -DBUILD_TENSORFLOW_OPS=OFF \
    -DBUILD_UNIT_TESTS=OFF \
    -DBUILD_WEBRTC=OFF \
    -DBUNDLE_OPEN3D_ML=OFF \
    -DPython3_EXECUTABLE="$PYTHON_BIN"

cmake --build "$SOURCE_DIR/build" --parallel "$OPEN3D_BUILD_JOBS"
cmake --build "$SOURCE_DIR/build" --target install-pip-package \
    --parallel "$OPEN3D_BUILD_JOBS"

"$PYTHON_BIN" -c "import open3d; print('Open3D installed:', open3d.__version__)"
