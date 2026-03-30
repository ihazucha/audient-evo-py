# My EVO4 Audio Setup

Linux audio configuration for the Audient EVO4 USB interface on
Arch Linux with PipeWire 1.6+ and WirePlumber 0.5+.

## Overview

The EVO4 exposes 4 USB audio channels but only has 2 physical
inputs and 2 physical outputs. Without configuration, PipeWire sees
a "Surround 4.0" device and upmixes stereo audio across all 4 channels,
causing volume/channel issues.

This setup uses **PipeWire loopback modules** to present clean stereo
nodes to applications while routing audio correctly to the 4-channel
ALSA device underneath.

## Signal Flow

### Playback

```
 Application (Firefox, Discord, mpv, ...)
 Sends stereo audio (FL, FR)
      │
      ▼
┌─────────────────────────────────┐
│  evo4_stereo_output             │  Virtual 2ch sink (loopback module)
│  Audio/Sink — FL, FR            │  Apps connect here as their output
│                                 │
│  Internally remaps to 4ch:      │
│  FL, FR, FL, FR                 │  Duplicates L/R into channels 3-4
│  stream.dont-remix = true       │  Prevents PipeWire from upmixing
│  node.passive = true            │  Doesn't block device suspension
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  alsa_output.usb-Audient_EVO4  │  Raw ALSA 4ch node
│  -00.analog-surround-40        │  Kernel snd-usb-audio driver
└────────────┬────────────────────┘
             │
             ▼
     EVO4 DAC → Headphones / Speakers
     (hardware uses FL+FR only, ignores ch 3-4)
```

### Capture

```
     EVO4 ADC ← Microphone / Instrument inputs
     (2 physical inputs mapped to FL+FR, ch 3-4 unused)
             │
             ▼
┌─────────────────────────────────┐
│  alsa_input.usb-Audient_EVO4   │  Raw ALSA 4ch node
│  -00.analog-surround-40        │  Kernel snd-usb-audio driver
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  evo4_stereo_mic                │  Virtual 2ch source (loopback module)
│  Audio/Source — FL, FR          │  Apps see a clean stereo mic
│                                 │
│  Captures 4ch from ALSA node,   │
│  exposes only FL+FR to apps     │
│  stream.dont-remix = true       │
└────────────┬────────────────────┘
             │
             ▼
 Application (Discord, OBS, Audacity, ...)
 Receives stereo mic input
```

### Full System Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Applications                                │
│   Firefox  Discord  mpv  OBS  Steam  Chromium  Spotify  ...         │
│                                                                     │
│   All use PulseAudio API → pipewire-pulse translates transparently  │
└────────────────────┬────────────────────────────┬───────────────────┘
                     │ playback                   │ capture
                     ▼                            │
┌────────────────────────────────┐                │
│     evo4_stereo_output         │                │
│     (loopback sink, 2ch)       │                │
│     FL,FR → FL,FR,FL,FR        │                │
└────────────┬───────────────────┘                │
             │                                    │
             ▼                                    │
┌────────────────────────────────┐  ┌─────────────┴──────────────────┐
│  ALSA output node (4ch)        │  │  ALSA input node (4ch)         │
│  alsa_output.usb-Audient_EVO4  │  │  alsa_input.usb-Audient_EVO4   │
│  -00.analog-surround-40        │  │  -00.analog-surround-40        │
└────────────┬───────────────────┘  └─────────────┬──────────────────┘
             │                                    │
             │           USB (snd-usb-audio)      │
             ▼                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Audient EVO4                                 │
│                                                                     │
│  Outputs: Headphones (FL+FR)     Inputs: Mic/Line 1 (FL)           │
│           Speakers (FL+FR)               Mic/Line 2 (FR)           │
│                                                                     │
│  Hardware controls (via evoctl.py + evo4_raw kernel module):        │
│    Volume, Gain, Monitor Mix, Mute, Phantom 48V                    │
└─────────────────────────────────────────────────────────────────────┘

Other audio devices (Realtek onboard, HDMI) remain available and
unaffected. The EVO4 configs only match "usb-Audient_EVO4" nodes.
```

## Configuration Files

Three config files, two support files:

| File | Location | Purpose |
|------|----------|---------|
| `evo4-stereo.conf` | `~/.config/pipewire/pipewire.conf.d/` | Loopback modules — creates `evo4_stereo_output` (2ch sink) and `evo4_stereo_mic` (2ch source) |
| `51-evo4.conf` | `~/.config/wireplumber/wireplumber.conf.d/` | WirePlumber rules — disables `node.pause-on-idle` on EVO4 nodes to prevent clicks/pops |
| `alsa-soft-mixer.conf` | `~/.config/wireplumber/wireplumber.conf.d/` | Forces software volume on all ALSA devices (not EVO4-specific) |
| `evo4-setup.sh` | `~/.local/bin/` | Helper script — finds EVO4 loopback nodes and sets them as default via `wpctl` |
| `evo4-setup.service` | `~/.config/systemd/user/` | Runs `evo4-setup.sh` at login to ensure EVO4 is the default device |

### evo4-stereo.conf

Creates two PipeWire loopback modules:

**Output loopback** (`evo4_stereo_output`):
- Presents a stereo `Audio/Sink` to applications (2ch: FL, FR)
- Forwards to the raw 4ch ALSA output, mapping stereo to `FL FR FL FR`
- `stream.dont-remix = true` prevents PipeWire from trying to upmix
- `node.passive = true` allows the ALSA device to suspend when nothing plays

**Input loopback** (`evo4_stereo_mic`):
- Captures from the raw 4ch ALSA input (FL, FR, RL, RR)
- Presents only FL+FR as a stereo `Audio/Source` to applications
- Applications see "EVO4 Stereo Microphone" instead of a confusing 4ch source

### 51-evo4.conf

WirePlumber 0.5+ device rules in SPA-JSON format. Matches all ALSA nodes
whose name starts with `alsa_*.usb-Audient_EVO4-00.*` and sets:

- `node.pause-on-idle = false` — prevents WirePlumber from suspending
  the USB device when no audio is playing, which avoids audible clicks
  when playback resumes

### alsa-soft-mixer.conf

Applies to ALL ALSA cards (not just EVO4). Forces `api.alsa.soft-mixer = true`
so volume control happens in software (PipeWire) rather than the hardware
mixer. This avoids hardware mixer quirks across different audio devices
while keeping behavior consistent.

For the EVO4 specifically, this means PipeWire handles digital volume while
the hardware volume knob and `evoctl.py` control the analog output stage
independently. For best audio quality, keep PipeWire volume at 100% and
use the hardware volume.

### evo4-setup.sh + evo4-setup.service

The setup script detects the EVO4 loopback nodes and sets them as the
system default sink and source via `wpctl set-default`. These defaults
persist in WirePlumber's state file (`~/.local/state/wireplumber/`).

The systemd user service runs the script at login (after PipeWire and
WirePlumber start). This ensures the EVO4 is the default device even
after WirePlumber state is cleared.

The script can also be run manually:
```bash
evo4-setup.sh
```

## Why Loopback Instead of Pro-Audio Profile

Two approaches exist for handling the 4ch-to-2ch mapping:

| | Loopback (this setup) | Pro-audio profile |
|---|---|---|
| How | Virtual 2ch sink/source, forwards to 4ch ALSA | Exposes raw ports (AUX0-3), WP links AUX0+1 |
| Latency | +1 quantum (~5 ms at 256/48000) | Direct, no extra hop |
| App compat | Apps see "EVO4 Stereo Output" | Apps see "AUX0, AUX1" |
| pavucontrol | Clean stereo device | Raw ports, less intuitive |
| DAW use | Hides channels 3-4 | Full access to all channels |

Loopback is better for daily desktop use. The extra ~5 ms latency is
imperceptible for music, calls, and video. Apps and pavucontrol show
a clean stereo device with a descriptive name.

Pro-audio profile is better for DAW workflows (Ardour, REAPER) where
you need direct access to all 4 channels with minimum latency.

## Volume Control

Two independent volume controls exist:

**Software volume (PipeWire)**:
- Controlled via pavucontrol, system tray, or `wpctl set-volume`
- Applied digitally before the DAC — reduces effective bit depth
- Managed by `alsa-soft-mixer.conf`

**Hardware volume (EVO4)**:
- Controlled via the physical knob or `evoctl.py set volume <0-100>`
- Applied in the analog output stage — preserves full bit depth
- Uses the `evo4_raw` kernel module for USB control transfers

For best audio quality: set PipeWire volume to 100%, control volume
with the hardware knob or evoctl.

## Installation

```bash
cd dev/linux-audio
bash evo4_wireplumber_setup.sh
```

The installer backs up existing configs to `~/.config/evo4-audio-backup/`,
installs the new configs, removes deprecated files, restarts the audio
stack, and sets defaults.

## Troubleshooting

**No sound / wrong default device:**
```bash
wpctl status                    # check which sink is default (marked with *)
evo4-setup.sh                   # re-set EVO4 as default
```

**Clicks/pops when playback starts:**
```bash
# Check that pause-on-idle is disabled:
pw-cli dump Node | grep -A5 evo4 | grep pause
# Should show: node.pause-on-idle = "false"
```

**EVO4 not detected:**
```bash
# Check USB connection:
lsusb | grep Audient

# Check ALSA sees it:
aplay -l | grep EVO4

# Check PipeWire nodes:
pw-cli list-objects Node | grep EVO4
```

**Verify the full audio path:**
```bash
pw-top                          # live view of PipeWire graph activity
pw-dot | dot -Tpng > graph.png  # visual graph of all nodes and links
```

## Removed Configs

These files were part of earlier setup attempts and have been removed:

| File | Why removed |
|------|-------------|
| `evo4-alsa-profiles.conf` | Referenced `device.profile-set = "evo4-stereo.conf"` — no such profile set file exists; ALSA silently fell back to defaults |
| `evo4-defaults.conf` | Set PulseAudio defaults via `pulse.properties` — replaced by `wpctl set-default` which persists in WP state |
| `51-evo4-config.lua` | Used WirePlumber 0.4 Lua API (`alsa_monitor.rules`, `table.insert`) — WP 0.5+ ignores Lua configs entirely, so these rules were silently not applied |
| `evo4-virtual-stereo` (null sink) | Unused virtual Audio/Duplex device that appeared in `pactl list sinks` but nothing routed to it |
