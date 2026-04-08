#!/bin/bash
set -euo pipefail

MODULE_NAME="evo_raw"
MODULE_VERSION="0.1"
SRC_DIR="/usr/src/${MODULE_NAME}-${MODULE_VERSION}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)."
    exit 1
fi

# Check required dependencies
if ! command -v make &>/dev/null; then
    echo "Error: 'make' is not installed."
    echo "Install it with your package manager (e.g. apt install build-essential, pacman -S base-devel)"
    exit 1
fi

# Check kernel headers
KDIR="/lib/modules/$(uname -r)/build"
if [[ ! -d "$KDIR" ]]; then
    echo "Error: kernel headers not found at $KDIR"
    echo "Install them (e.g. apt install linux-headers-\$(uname -r), pacman -S linux-headers)"
    exit 1
fi

# Check for DKMS (optional but recommended)
USE_DKMS=0
if command -v dkms &>/dev/null; then
    USE_DKMS=1
else
    echo "Warning: 'dkms' is not installed."
    echo "  Kernel modules are version-stamped: after a kernel update the module"
    echo "  will stop loading and you will need to re-run this install script."
    echo "  DKMS automates that rebuild. It is recommended:"
    echo "    apt install dkms  OR  pacman -S dkms"
    echo ""
    read -p "Continue without DKMS? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Device selection - discover available devices from udev rule files
AVAILABLE=()
for rule in "$SCRIPT_DIR"/99-evo*.rules; do
    [[ -f "$rule" ]] || continue
    dev=$(basename "$rule" .rules)
    dev="${dev#99-}"
    AVAILABLE+=("$dev")
done

if [[ ${#AVAILABLE[@]} -eq 0 ]]; then
    echo "Error: no 99-evo*.rules files found in $SCRIPT_DIR"
    exit 1
fi

echo "Which device do you want to set up?"
for i in "${!AVAILABLE[@]}"; do
    echo "  $((i+1))) ${AVAILABLE[$i]}"
done
read -p "Select [1-${#AVAILABLE[@]}]: " -n 1 -r DEVICE_CHOICE
echo ""

if ! [[ "$DEVICE_CHOICE" =~ ^[0-9]+$ ]] || (( DEVICE_CHOICE < 1 || DEVICE_CHOICE > ${#AVAILABLE[@]} )); then
    echo "Invalid choice."
    exit 1
fi

SELECTED="${AVAILABLE[$((DEVICE_CHOICE-1))]}"
DEVICES=("$SELECTED")

if [[ $USE_DKMS -eq 1 ]]; then
    # DKMS install

    # Remove previous version if installed
    if dkms status "${MODULE_NAME}/${MODULE_VERSION}" 2>/dev/null | grep -q "${MODULE_NAME}"; then
        echo "Removing existing DKMS module..."
        dkms remove "${MODULE_NAME}/${MODULE_VERSION}" --all
    fi

    # Also remove legacy evo4_raw if present
    if dkms status "evo4_raw/${MODULE_VERSION}" 2>/dev/null | grep -q "evo4_raw"; then
        echo "Removing legacy evo4_raw DKMS module..."
        dkms remove "evo4_raw/${MODULE_VERSION}" --all
    fi
    if lsmod | grep -q "^evo4_raw"; then
        echo "Unloading legacy evo4_raw module..."
        rmmod evo4_raw
    fi

    # Copy source to /usr/src
    echo "Copying module source to ${SRC_DIR}..."
    rm -rf "$SRC_DIR"
    mkdir -p "$SRC_DIR"
    cp "$SCRIPT_DIR"/{evo_raw.c,Makefile,dkms.conf} "$SRC_DIR/"

    echo "Adding module to DKMS..."
    dkms add "${MODULE_NAME}/${MODULE_VERSION}"

    echo "Building module..."
    dkms build "${MODULE_NAME}/${MODULE_VERSION}"

    echo "Installing module..."
    dkms install "${MODULE_NAME}/${MODULE_VERSION}"
else
    # Manual install (no DKMS)

    # Remove legacy evo4_raw if present
    if lsmod | grep -q "^evo4_raw"; then
        echo "Unloading legacy evo4_raw module..."
        rmmod evo4_raw
    fi

    echo "Building module..."
    make -C "$SCRIPT_DIR" all

    echo "Installing module..."
    make -C "$SCRIPT_DIR" install

    # Enable auto-load on boot
    echo "$MODULE_NAME" > /etc/modules-load.d/evo_raw.conf
fi

# Install udev rules for selected devices
for dev in "${DEVICES[@]}"; do
    UDEV_RULE="99-${dev}.rules"
    echo "Installing udev rule for ${dev}..."
    cp "$SCRIPT_DIR/${UDEV_RULE}" /etc/udev/rules.d/
done
udevadm control --reload-rules

# Load module
echo "Loading module..."
modprobe "$MODULE_NAME"

# Add user to dialout group
if [[ -n "${SUDO_USER:-}" ]]; then
    if groups "$SUDO_USER" | grep -qw 'dialout'; then
        echo "User '$SUDO_USER' is already in the 'dialout' group."
    else
        echo ""
        echo "Users must be in the 'dialout' group to access /dev/${SELECTED} without sudo."
        read -p "Add '$SUDO_USER' to the 'dialout' group now? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            usermod -a -G dialout "$SUDO_USER"
            echo "Done. Log out and back in (or reboot) for the group change to take effect."
        else
            echo "Skipped. Run manually when ready: sudo usermod -a -G dialout $SUDO_USER"
        fi
    fi
fi

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
        EVOCTL_PATH="$TARGET_HOME/.local/bin/evoctl"

        if [[ -f $EVOCTL_PATH ]]; then
            SYSTEMD_USER_DIR="$TARGET_HOME/.config/systemd/user"
            TARGET_UID=$(id -u "$TARGET_USER")

            for dev in "${DEVICES[@]}"; do
                SERVICE="${dev}-load-config.service"
                echo "Setting up auto-load for ${dev} (user: $TARGET_USER)"

                install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
                    "$SCRIPT_DIR/${SERVICE}" \
                    "$SYSTEMD_USER_DIR/${SERVICE}"

                sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user daemon-reload
                sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user enable "${SERVICE}"
            done

            echo "Auto-load config enabled."
            echo ""
            echo "To test, reconnect your device or log out and back in."
            for dev in "${DEVICES[@]}"; do
                echo "View logs with: journalctl --user -u ${dev}-load-config.service -f"
            done
        else
            echo "Error: 'evoctl' not found at $EVOCTL_PATH"
            echo "Install it first with: pipx install ."
            echo "Skipping auto-load setup."
        fi
    fi
fi

echo ""
echo "Done. ${MODULE_NAME} is installed and loaded."
for dev in "${DEVICES[@]}"; do
    echo "  /dev/${dev} will be available when the device is connected."
done
if [[ $USE_DKMS -eq 1 ]]; then
    echo "  The module will auto-rebuild on kernel updates (DKMS)."
else
    echo "  Note: Without DKMS, re-run this install script after each kernel update."
fi
