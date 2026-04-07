#!/usr/bin/env bash
# install.sh - Install Audient EVO PipeWire/WirePlumber config
#
# Installs audio configuration for the selected EVO device on
# PipeWire + WirePlumber 0.5+.
#
# What it does:
#   1. Backs up existing configs
#   2. Installs loopback modules, WP rules, soft mixer config
#   3. Installs setup script + systemd service
#   4. Restarts PipeWire + WirePlumber
#   5. Sets EVO stereo nodes as default devices
#
# Usage: bash install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$HOME/.config/evo-audio-backup/$(date +%Y%m%d-%H%M%S)"

PW_CONF="$HOME/.config/pipewire/pipewire.conf.d"
WP_CONF="$HOME/.config/wireplumber/wireplumber.conf.d"
SYSTEMD_USER="$HOME/.config/systemd/user"
LOCAL_BIN="$HOME/.local/bin"

info() { echo -e "\033[1;34m==>\033[0m $*"; }
warn() { echo -e "\033[1;33m==> WARNING:\033[0m $*"; }
ok() { echo -e "\033[1;32m  ->\033[0m $*"; }

# Device selection - list available configs dynamically
AVAILABLE=()
for dir in "$SCRIPT_DIR"/*/; do
    dev=$(basename "$dir")
    if [[ -f "$dir/${dev}-stereo.conf" ]]; then
        AVAILABLE+=("$dev")
    fi
done

if [[ ${#AVAILABLE[@]} -eq 0 ]]; then
    echo "No device configs found in $SCRIPT_DIR"
    exit 1
fi

echo "Which device do you want to set up?"
for i in "${!AVAILABLE[@]}"; do
    echo "  $((i+1))) ${AVAILABLE[$i]^^}"
done
read -p "Select [1-${#AVAILABLE[@]}]: " -n 1 -r DEVICE_CHOICE
echo ""

idx=$((DEVICE_CHOICE - 1))
if [[ $idx -lt 0 || $idx -ge ${#AVAILABLE[@]} ]]; then
    echo "Invalid choice."
    exit 1
fi

dev="${AVAILABLE[$idx]}"
DEV_DIR="$SCRIPT_DIR/$dev"
DEV_UPPER="${dev^^}"

# Backup existing configs
info "Backing up existing configs to $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

for f in \
  "$PW_CONF/${dev}-stereo.conf" \
  "$WP_CONF/51-${dev}.conf" \
  "$WP_CONF/alsa-soft-mixer.conf" \
  "$SYSTEMD_USER/${dev}-setup.service" \
  "$LOCAL_BIN/${dev}-setup.sh"; do
  if [[ -f "$f" ]]; then
    rel="${f#"$HOME"/}"
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp "$f" "$BACKUP_DIR/$rel"
  fi
done
ok "Backup complete"

# Install configs
info "Installing PipeWire loopback config for $DEV_UPPER"
mkdir -p "$PW_CONF"
cp "$DEV_DIR/${dev}-stereo.conf" "$PW_CONF/${dev}-stereo.conf"
ok "${dev}-stereo.conf -> $PW_CONF/"

info "Installing WirePlumber device rules for $DEV_UPPER"
mkdir -p "$WP_CONF"
cp "$DEV_DIR/51-${dev}.conf" "$WP_CONF/51-${dev}.conf"
ok "51-${dev}.conf -> $WP_CONF/"

info "Installing shared ALSA soft mixer config"
cp "$SCRIPT_DIR/alsa-soft-mixer.conf" "$WP_CONF/alsa-soft-mixer.conf"
ok "alsa-soft-mixer.conf -> $WP_CONF/"

info "Installing setup script for $DEV_UPPER"
mkdir -p "$LOCAL_BIN"
cp "$DEV_DIR/${dev}-setup.sh" "$LOCAL_BIN/${dev}-setup.sh"
chmod +x "$LOCAL_BIN/${dev}-setup.sh"
ok "${dev}-setup.sh -> $LOCAL_BIN/"

info "Installing systemd user service for $DEV_UPPER"
mkdir -p "$SYSTEMD_USER"
cp "$DEV_DIR/${dev}-setup.service" "$SYSTEMD_USER/${dev}-setup.service"
systemctl --user daemon-reload
systemctl --user enable "${dev}-setup.service" 2>/dev/null
ok "${dev}-setup.service enabled (sets defaults at login)"

# Restart audio stack
info "Restarting PipeWire and WirePlumber"
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service

sleep 3

# Set defaults
info "Setting $DEV_UPPER as default audio device"

get_node_id() {
    wpctl status 2>/dev/null | grep -m1 "$1" | grep -oP '\d+(?=\.)' | head -1 || true
}

SINK_ID=$(get_node_id "${dev}_main_output")

if [[ -n "${SINK_ID:-}" ]]; then
    wpctl set-default "$SINK_ID"
    ok "Default sink: $DEV_UPPER Main Output (id=$SINK_ID)"
else
    warn "Could not find $DEV_UPPER ALSA output - is the device connected?"
    warn "Run '${dev}-setup.sh' manually after connecting the device"
fi

# Try to find the mic source - naming varies by device
for src in "${dev}_mic" "${dev}_mic_1_2"; do
    SOURCE_ID=$(get_node_id "$src")
    if [[ -n "${SOURCE_ID:-}" ]]; then
        wpctl set-default "$SOURCE_ID"
        ok "Default source: $src (id=$SOURCE_ID)"
        break
    fi
done

# Summary
echo ""
info "Configuration summary"
echo ""
echo "  Installed:"
echo "    $PW_CONF/${dev}-stereo.conf"
echo "    $WP_CONF/51-${dev}.conf"
echo "    $WP_CONF/alsa-soft-mixer.conf"
echo "    $LOCAL_BIN/${dev}-setup.sh"
echo "    $SYSTEMD_USER/${dev}-setup.service"
echo ""
echo "  Verify:"
echo "    wpctl status"
echo "    pactl info | grep 'Default Sink'"
echo "    pw-top"
echo ""
echo "  Backup at: $BACKUP_DIR"
echo ""
info "Done!"
