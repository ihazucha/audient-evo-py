#!/bin/bash
set -euo pipefail

MODULE_NAME="evo_raw"
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

# Also unload legacy module
if lsmod | grep -q "^evo4_raw"; then
  echo "Unloading legacy evo4_raw module..."
  rmmod evo4_raw
fi

# Remove from DKMS
if command -v dkms &>/dev/null && dkms status "${MODULE_NAME}/${MODULE_VERSION}" 2>/dev/null | grep -q "${MODULE_NAME}"; then
  echo "Removing from DKMS..."
  dkms remove "${MODULE_NAME}/${MODULE_VERSION}" --all
fi

# Remove legacy DKMS
if command -v dkms &>/dev/null && dkms status "evo4_raw/${MODULE_VERSION}" 2>/dev/null | grep -q "evo4_raw"; then
  echo "Removing legacy evo4_raw from DKMS..."
  dkms remove "evo4_raw/${MODULE_VERSION}" --all
fi

# Remove source
for src in "$SRC_DIR" "/usr/src/evo4_raw-${MODULE_VERSION}"; do
  if [[ -d "$src" ]]; then
    echo "Removing source from ${src}..."
    rm -rf "$src"
  fi
done

# Remove udev rules
for rules in /etc/udev/rules.d/99-evo*.rules; do
  if [[ -f "$rules" ]]; then
    echo "Removing udev rule $(basename "$rules")..."
    rm "$rules"
  fi
done
udevadm control --reload-rules 2>/dev/null || true

# Remove systemd user services if installed
if [[ -n "${SUDO_USER:-}" ]]; then
  TARGET_USER="$SUDO_USER"
  TARGET_HOME=$(eval echo ~"$TARGET_USER")

  for SYSTEMD_SERVICE in "$TARGET_HOME"/.config/systemd/user/evo*-load-config.service; do
    if [[ -f "$SYSTEMD_SERVICE" ]]; then
      service=$(basename "$SYSTEMD_SERVICE")
      echo "Disabling and removing systemd service ${service} for user '$TARGET_USER'..."
      sudo -u "$TARGET_USER" systemctl --user disable "$service" 2>/dev/null || true
      rm "$SYSTEMD_SERVICE"
    fi
  done
fi

echo "Done. ${MODULE_NAME} has been fully removed."
