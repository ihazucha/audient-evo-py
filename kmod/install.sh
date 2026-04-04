#!/bin/bash
set -euo pipefail

MODULE_NAME="evo4_raw"
MODULE_VERSION="0.1"
SRC_DIR="/usr/src/${MODULE_NAME}-${MODULE_VERSION}"
UDEV_RULE="99-evo4.rules"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)."
    exit 1
fi

# Check dependencies
for cmd in dkms make; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: '$cmd' is not installed."
        echo "Install it with your package manager (e.g. pacman -S dkms base-devel)"
        exit 1
    fi
done

# Check kernel headers
KDIR="/lib/modules/$(uname -r)/build"
if [[ ! -d "$KDIR" ]]; then
    echo "Error: kernel headers not found at $KDIR"
    echo "Install them (e.g. pacman -S linux-headers)"
    exit 1
fi

# Remove previous version if installed
if dkms status "${MODULE_NAME}/${MODULE_VERSION}" 2>/dev/null | grep -q "${MODULE_NAME}"; then
    echo "Removing existing DKMS module..."
    dkms remove "${MODULE_NAME}/${MODULE_VERSION}" --all
fi

# Copy source to /usr/src
echo "Copying module source to ${SRC_DIR}..."
rm -rf "$SRC_DIR"
mkdir -p "$SRC_DIR"
cp "$SCRIPT_DIR"/{evo4_raw.c,Makefile,dkms.conf} "$SRC_DIR/"

# DKMS: add, build, install
echo "Adding module to DKMS..."
dkms add "${MODULE_NAME}/${MODULE_VERSION}"

echo "Building module..."
dkms build "${MODULE_NAME}/${MODULE_VERSION}"

echo "Installing module..."
dkms install "${MODULE_NAME}/${MODULE_VERSION}"

# Install udev rule
echo "Installing udev rule..."
cp "$SCRIPT_DIR/${UDEV_RULE}" /etc/udev/rules.d/
udevadm control --reload-rules

# Load module
echo "Loading module..."
modprobe "$MODULE_NAME"

# Optional: Setup auto-load config on device connection
echo ""
read -p "Enable auto-load of saved config when device is connected? (y/n) " -n 1 -r SETUP_AUTOLOAD
echo ""

if [[ $SETUP_AUTOLOAD =~ ^[Yy]$ ]]; then
    if [[ -n "${SUDO_USER:-}" ]]; then
        TARGET_USER="$SUDO_USER"
    else
        echo "Error: Could not determine user (not run via sudo?)."
        echo "Skipping auto-load setup."
    fi

    if [[ -n "${TARGET_USER:-}" ]]; then
        TARGET_HOME=$(eval echo ~"$TARGET_USER")
        EVOCTL_PATH="/home/$TARGET_USER/.local/bin/evoctl"

        # Check if evoctl is available in TARGET_USER's environment
        if [[ -f $EVOCTL_PATH ]]; then
            SYSTEMD_USER_DIR="$TARGET_HOME/.config/systemd/user"
            echo "Setting up auto-load for user: $TARGET_USER"
            echo "  Service file: $SYSTEMD_USER_DIR/evo4-load-config.service"

            # Install the service file
            mkdir -p "$SYSTEMD_USER_DIR"
            cp "$SCRIPT_DIR/evo4-load-config.service" "$SYSTEMD_USER_DIR/"
            chown "$TARGET_USER:$TARGET_USER" "$SYSTEMD_USER_DIR/evo4-load-config.service"

            echo "Auto-load config enabled."
            echo ""
            echo "To test, reconnect your EVO4 device."
            echo "View logs with: journalctl --user -u evo4-load-config.service -f"
        else
            echo "Error: 'evoctl' not found in $TARGET_USER's PATH."
            echo "Install it first with: pipx install ."
            echo "Skipping auto-load setup."
        fi
    fi
fi

echo ""
echo "Done. ${MODULE_NAME} is installed and loaded."
echo "Users in the 'dialout' group can access /dev/evo4 when the device is connected."
echo "The module will auto-rebuild on kernel updates."
