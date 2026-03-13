#!/bin/bash
set -euo pipefail

MODULE_NAME="evo4_raw"
MODULE_VERSION="0.1"
SRC_DIR="/usr/src/${MODULE_NAME}-${MODULE_VERSION}"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)."
    exit 1
fi

# Unload module if loaded
if lsmod | grep -q "^${MODULE_NAME}"; then
    echo "Unloading module..."
    rmmod "$MODULE_NAME"
fi

# Remove from DKMS
if command -v dkms &>/dev/null && dkms status "${MODULE_NAME}/${MODULE_VERSION}" 2>/dev/null | grep -q "${MODULE_NAME}"; then
    echo "Removing from DKMS..."
    dkms remove "${MODULE_NAME}/${MODULE_VERSION}" --all
fi

# Remove source
if [[ -d "$SRC_DIR" ]]; then
    echo "Removing source from ${SRC_DIR}..."
    rm -rf "$SRC_DIR"
fi

# Remove udev rule
if [[ -f /etc/udev/rules.d/99-evo4.rules ]]; then
    echo "Removing udev rule..."
    rm /etc/udev/rules.d/99-evo4.rules
    udevadm control --reload-rules
fi

echo "Done. ${MODULE_NAME} has been fully removed."
