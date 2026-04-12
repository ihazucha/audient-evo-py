#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-$repo_root/screenshots}"
terminal_bin="${TERMINAL_BIN:-alacritty}"
window_class="${WINDOW_CLASS:-evo-docshot}"
window_width="${WINDOW_WIDTH:-1180}"
window_height="${WINDOW_HEIGHT:-920}"
window_x="${WINDOW_X:-260}"
window_y="${WINDOW_Y:-80}"
terminal_columns="${TERMINAL_COLUMNS:-85}"
terminal_lines="${TERMINAL_LINES:-30}"

mkdir -p "$output_dir"

for cmd in "$terminal_bin" hyprctl grim jq wtype; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "missing: $cmd" >&2
    exit 1
  fi
done

client_by_title() {
  local title="$1"
  hyprctl -j clients | jq -c --arg title "$title" '.[] | select(.title == $title)' | head -n1
}

wait_for_client() {
  local title="$1"
  local client=""
  for _ in $(seq 1 80); do
    client="$(client_by_title "$title")"
    if [[ -n "$client" ]]; then
      printf '%s\n' "$client"
      return 0
    fi
    sleep 0.15
  done
  return 1
}

focused_monitor() {
  hyprctl -j monitors | jq -c 'if length == 0 then empty else ((map(select(.focused)) | .[0]) // .[0]) end'
}

focus_client() {
  local address="$1"
  hyprctl dispatch focuswindow "address:$address" >/dev/null
}

close_window() {
  local pid="$1"
  local address="${2:-}"
  if [[ -n "$address" ]]; then
    hyprctl dispatch closewindow "address:$address" >/dev/null 2>&1 || true
  fi
  kill "$pid" >/dev/null 2>&1 || true
  wait "$pid" 2>/dev/null || true
}

window_inset() {
  local border rounding
  border="$(hyprctl getoption general:border_size -j | jq '.int')"
  rounding="$(hyprctl getoption decoration:rounding -j | jq '.int')"
  echo $(( border + rounding ))
}

capture_state() {
  local name="$1"
  local device="$2"
  local key_action="${3:-}"
  local title="evo-shot-$name"
  local screenshot="$output_dir/$name.png"
  local terminal_args=(
    --title "$title"
    --class "$window_class,$window_class"
    -o "window.dimensions.columns=$terminal_columns"
    -o "window.dimensions.lines=$terminal_lines"
    -o "font.size=18"
    -o "window.opacity=1"
    -o "window.padding.x=8"
    -o "window.padding.y=8"
  )

  env -u NO_COLOR COLORTERM=truecolor TERM=xterm-256color "$terminal_bin" \
    "${terminal_args[@]}" \
    -e bash -lc "cd '$repo_root' && python evotui.py --demo --device $device" >/dev/null 2>&1 &
  local term_pid=$!

  local client
  client="$(wait_for_client "$title")"
  local address
  address="$(printf '%s' "$client" | jq -r '.address')"

  local monitor
  monitor="$(focused_monitor)"
  local monitor_x monitor_y monitor_w monitor_h monitor_scale
  monitor_x="$(printf '%s' "$monitor" | jq -r '.x')"
  monitor_y="$(printf '%s' "$monitor" | jq -r '.y')"
  monitor_w="$(printf '%s' "$monitor" | jq -r '.width')"
  monitor_h="$(printf '%s' "$monitor" | jq -r '.height')"
  monitor_scale="$(printf '%s' "$monitor" | jq -r '.scale')"
  local logical_monitor_w logical_monitor_h
  logical_monitor_w="$(awk -v w="$monitor_w" -v s="$monitor_scale" 'BEGIN { printf "%d", w / s }')"
  logical_monitor_h="$(awk -v h="$monitor_h" -v s="$monitor_scale" 'BEGIN { printf "%d", h / s }')"

  local target_w target_h target_x target_y max_x max_y
  target_w="$window_width"
  target_h="$window_height"
  if (( target_w > logical_monitor_w )); then target_w="$logical_monitor_w"; fi
  if (( target_h > logical_monitor_h )); then target_h="$logical_monitor_h"; fi
  max_x=$((monitor_x + logical_monitor_w - target_w))
  max_y=$((monitor_y + logical_monitor_h - target_h))
  target_x=$((monitor_x + window_x))
  target_y=$((monitor_y + window_y))
  if (( target_x < monitor_x )); then target_x="$monitor_x"; fi
  if (( target_y < monitor_y )); then target_y="$monitor_y"; fi
  if (( target_x > max_x )); then target_x="$max_x"; fi
  if (( target_y > max_y )); then target_y="$max_y"; fi

  hyprctl dispatch setfloating "address:$address" >/dev/null
  hyprctl dispatch resizewindowpixel "exact $target_w $target_h,address:$address" >/dev/null
  hyprctl dispatch movewindowpixel "exact $target_x $target_y,address:$address" >/dev/null

  sleep 0.9
  focus_client "$address"
  sleep 0.6

  if [[ -n "$key_action" ]]; then
    eval "$key_action"
    sleep 0.7
  fi

  client="$(hyprctl -j clients | jq -c --arg addr "$address" '.[] | select(.address == $addr)' | head -n1)"
  local x y w h
  x="$(printf '%s' "$client" | jq -r '.at[0]')"
  y="$(printf '%s' "$client" | jq -r '.at[1]')"
  w="$(printf '%s' "$client" | jq -r '.size[0]')"
  h="$(printf '%s' "$client" | jq -r '.size[1]')"

  local inset
  inset="$(window_inset)"
  local capture_x capture_y capture_w capture_h
  capture_x=$((x + inset))
  capture_y=$((y + inset))
  capture_w=$((w - 2 * inset))
  capture_h=$((h - 2 * inset))

  grim -g "$capture_x,$capture_y ${capture_w}x${capture_h}" "$screenshot"
  echo "  saved: $screenshot"

  close_window "$term_pid" "$address"
}

for device in evo4 evo8; do
  printf '%s:\n' "$device"
  capture_state "${device}_controls" "$device"
  capture_state "${device}_mixer"    "$device" "wtype -k Tab"
done

printf 'Done. Screenshots in %s\n' "$output_dir"
