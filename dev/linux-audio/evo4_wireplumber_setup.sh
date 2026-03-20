#!/usr/bin/env bash
# evo4_wireplumber_setup.sh — Install Audient EVO4 PipeWire/WirePlumber config
#
# Installs a clean audio configuration for the EVO4 on PipeWire + WirePlumber 0.5+.
# Replaces the broken mix of Lua configs, phantom profile-set references, and
# unused virtual sinks with a minimal set of working configs.
#
# What it does:
#   1. Backs up existing configs
#   2. Installs 3 config files (loopback modules, WP rules, soft mixer)
#   3. Removes broken/deprecated configs
#   4. Installs setup script + systemd service
#   5. Restarts PipeWire + WirePlumber
#   6. Sets EVO4 stereo nodes as default devices
#
# Usage: bash evo4_wireplumber_setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$HOME/.config/evo4-audio-backup/$(date +%Y%m%d-%H%M%S)"

PW_CONF="$HOME/.config/pipewire/pipewire.conf.d"
PW_PULSE="$HOME/.config/pipewire/pipewire-pulse.conf.d"
WP_CONF="$HOME/.config/wireplumber/wireplumber.conf.d"
WP_LUA="$HOME/.config/wireplumber/main.lua.d"
SYSTEMD_USER="$HOME/.config/systemd/user"
LOCAL_BIN="$HOME/.local/bin"

info()  { echo -e "\033[1;34m==>\033[0m $*"; }
warn()  { echo -e "\033[1;33m==> WARNING:\033[0m $*"; }
ok()    { echo -e "\033[1;32m  ->\033[0m $*"; }

# ─── Backup existing configs ───────────────────────────────────────────────────

info "Backing up existing configs to $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

for f in \
    "$PW_CONF/evo4-stereo.conf" \
    "$PW_CONF/evo4-alsa-profiles.conf" \
    "$PW_PULSE/evo4-defaults.conf" \
    "$WP_CONF/alsa-soft-mixer.conf" \
    "$WP_CONF/51-evo4.conf" \
    "$WP_LUA/51-evo4-config.lua" \
    "$SYSTEMD_USER/evo4-setup.service" \
    "$LOCAL_BIN/evo4-setup.sh"; do
    if [[ -f "$f" ]]; then
        rel="${f#"$HOME"/}"
        mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
        cp "$f" "$BACKUP_DIR/$rel"
    fi
done
ok "Backup complete"

# ─── Install configs ──────────────────────────────────────────────────────────

info "Installing PipeWire loopback config"
mkdir -p "$PW_CONF"
cp "$SCRIPT_DIR/evo4-stereo.conf" "$PW_CONF/evo4-stereo.conf"
ok "evo4-stereo.conf -> $PW_CONF/"

info "Installing WirePlumber device rules"
mkdir -p "$WP_CONF"
cp "$SCRIPT_DIR/51-evo4.conf" "$WP_CONF/51-evo4.conf"
cp "$SCRIPT_DIR/alsa-soft-mixer.conf" "$WP_CONF/alsa-soft-mixer.conf"
ok "51-evo4.conf -> $WP_CONF/"
ok "alsa-soft-mixer.conf -> $WP_CONF/"

# ─── Remove deprecated configs ────────────────────────────────────────────────

info "Removing deprecated configs"

# Broken ALSA profile-set reference (points to nonexistent profile set)
if [[ -f "$PW_CONF/evo4-alsa-profiles.conf" ]]; then
    rm "$PW_CONF/evo4-alsa-profiles.conf"
    ok "Removed evo4-alsa-profiles.conf (broken profile-set reference)"
fi

# PulseAudio defaults (replaced by wpctl set-default)
if [[ -f "$PW_PULSE/evo4-defaults.conf" ]]; then
    rm "$PW_PULSE/evo4-defaults.conf"
    ok "Removed evo4-defaults.conf (defaults now set via wpctl)"
fi

# Dead WirePlumber 0.4 Lua config (WP 0.5+ ignores Lua entirely)
if [[ -f "$WP_LUA/51-evo4-config.lua" ]]; then
    rm "$WP_LUA/51-evo4-config.lua"
    ok "Removed 51-evo4-config.lua (dead WP 0.4 Lua code)"
fi

# Clean up empty directories
rmdir "$PW_PULSE" 2>/dev/null || true
rmdir "$WP_LUA" 2>/dev/null || true

# ─── Install setup script + service ───────────────────────────────────────────

info "Installing EVO4 setup script"
mkdir -p "$LOCAL_BIN"
cp "$SCRIPT_DIR/evo4-setup.sh" "$LOCAL_BIN/evo4-setup.sh"
chmod +x "$LOCAL_BIN/evo4-setup.sh"
ok "evo4-setup.sh -> $LOCAL_BIN/"

info "Installing systemd user service"
mkdir -p "$SYSTEMD_USER"
cp "$SCRIPT_DIR/evo4-setup.service" "$SYSTEMD_USER/evo4-setup.service"
systemctl --user daemon-reload
systemctl --user enable evo4-setup.service 2>/dev/null
ok "evo4-setup.service enabled (sets defaults at login)"

# ─── Restart audio stack ──────────────────────────────────────────────────────

info "Restarting PipeWire and WirePlumber"
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service

# Wait for graph to settle
sleep 3

# ─── Set EVO4 as default device ───────────────────────────────────────────────

info "Setting EVO4 as default audio device"

get_node_id() {
    wpctl status 2>/dev/null | grep -m1 "$1" | grep -oP '\d+(?=\.)' | head -1
}

SINK_ID=$(get_node_id "alsa_output.usb-Audient_EVO4-00")
SOURCE_ID=$(get_node_id "evo4_mic")

if [[ -n "${SINK_ID:-}" ]]; then
    wpctl set-default "$SINK_ID"
    ok "Default sink: EVO4 Main Output (id=$SINK_ID)"
else
    warn "Could not find EVO4 ALSA output — is the EVO4 connected?"
    warn "Run 'evo4-setup.sh' manually after connecting the device"
fi

if [[ -n "${SOURCE_ID:-}" ]]; then
    wpctl set-default "$SOURCE_ID"
    ok "Default source: EVO4 Microphone (id=$SOURCE_ID)"
else
    warn "Could not find evo4_mic"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────

echo ""
info "Configuration summary"
echo ""
echo "  Installed:"
echo "    $PW_CONF/evo4-stereo.conf"
echo "    $WP_CONF/51-evo4.conf"
echo "    $WP_CONF/alsa-soft-mixer.conf"
echo "    $LOCAL_BIN/evo4-setup.sh"
echo "    $SYSTEMD_USER/evo4-setup.service"
echo ""
echo "  Removed:"
echo "    evo4-alsa-profiles.conf   (broken profile-set ref)"
echo "    evo4-defaults.conf        (replaced by wpctl)"
echo "    51-evo4-config.lua        (dead WP 0.4 Lua code)"
echo ""
echo "  Verify:"
echo "    wpctl status"
echo "    pactl info | grep 'Default Sink'"
echo "    pw-top"
echo ""
echo "  Backup at: $BACKUP_DIR"
echo ""
info "Done!"
