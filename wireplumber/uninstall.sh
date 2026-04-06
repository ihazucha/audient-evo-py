#!/usr/bin/env bash
# uninstall.sh - Remove Audient EVO PipeWire/WirePlumber configs
#
# Dynamically discovers installed EVO configs and removes them.
# Usage: bash uninstall.sh

set -euo pipefail

PW_CONF="$HOME/.config/pipewire/pipewire.conf.d"
WP_CONF="$HOME/.config/wireplumber/wireplumber.conf.d"
SYSTEMD_USER="$HOME/.config/systemd/user"
LOCAL_BIN="$HOME/.local/bin"

info() { echo -e "\033[1;34m==>\033[0m $*"; }
warn() { echo -e "\033[1;33m==> WARNING:\033[0m $*"; }
ok() { echo -e "\033[1;32m  ->\033[0m $*"; }

removed=0

# Discover installed EVO device configs
for conf in "$PW_CONF"/evo*-stereo.conf; do
    [[ -f "$conf" ]] || continue
    dev=$(basename "$conf" -stereo.conf)
    info "Found $dev configs - removing"

    # PipeWire loopback config
    if [[ -f "$PW_CONF/${dev}-stereo.conf" ]]; then
        rm "$PW_CONF/${dev}-stereo.conf"
        ok "Removed $PW_CONF/${dev}-stereo.conf"
        removed=$((removed + 1))
    fi

    # WirePlumber device rules
    if [[ -f "$WP_CONF/51-${dev}.conf" ]]; then
        rm "$WP_CONF/51-${dev}.conf"
        ok "Removed $WP_CONF/51-${dev}.conf"
        removed=$((removed + 1))
    fi

    # Setup script
    if [[ -f "$LOCAL_BIN/${dev}-setup.sh" ]]; then
        rm "$LOCAL_BIN/${dev}-setup.sh"
        ok "Removed $LOCAL_BIN/${dev}-setup.sh"
        removed=$((removed + 1))
    fi

    # Systemd service (disable first)
    if [[ -f "$SYSTEMD_USER/${dev}-setup.service" ]]; then
        systemctl --user disable "${dev}-setup.service" 2>/dev/null || true
        rm "$SYSTEMD_USER/${dev}-setup.service"
        ok "Disabled and removed $SYSTEMD_USER/${dev}-setup.service"
        removed=$((removed + 1))
    fi
done

# Remove shared soft mixer config only if no EVO device configs remain
if [[ -f "$WP_CONF/alsa-soft-mixer.conf" ]]; then
    remaining=0
    for conf in "$WP_CONF"/51-evo*.conf; do
        [[ -f "$conf" ]] && remaining=$((remaining + 1))
    done
    if [[ $remaining -eq 0 ]]; then
        rm "$WP_CONF/alsa-soft-mixer.conf"
        ok "Removed $WP_CONF/alsa-soft-mixer.conf (no EVO devices remain)"
        removed=$((removed + 1))
    else
        info "Keeping alsa-soft-mixer.conf ($remaining EVO device(s) still configured)"
    fi
fi

if [[ $removed -eq 0 ]]; then
    info "No EVO WirePlumber configs found - nothing to remove."
    exit 0
fi

# Reload systemd and restart audio stack
systemctl --user daemon-reload 2>/dev/null || true
info "Restarting PipeWire and WirePlumber"
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service 2>/dev/null || true

echo ""
info "Done! Removed $removed file(s)."
echo "  Run 'wpctl status' to verify audio routing."
