# Linux Audio & the Audient EVO4

How the Linux audio stack works, how the EVO4 fits in, and how this machine
is configured. Written for this specific setup: Arch Linux, PipeWire 1.6.0,
WirePlumber 0.5+, Hyprland.

## The Linux Audio Stack

```
┌─────────────────────────────────────────────────────────────┐
│                       Applications                          │
│  Firefox, Discord, mpv, OBS, Steam, Chromium, ...           │
│                                                             │
│  Use one of:                                                │
│    • PulseAudio API  (most apps)                            │
│    • JACK API        (pro audio: Ardour, Carla)             │
│    • ALSA directly   (rare: aplay, some games)              │
│    • PipeWire native (newer apps, screen capture)           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │pipewire-pulse│  │ pipewire-jack│  │  PipeWire core   │  │
│  │(PA compat    │  │(JACK compat  │  │  (media server)  │  │
│  │ socket)      │  │ socket)      │  │                  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │            │
│         └─────────────────┴────────────────────┘            │
│                           │                                 │
│                    PipeWire daemon                           │
│              (graph-based audio router,                     │
│               mixer, resampler)                             │
│                           │                                 │
│                    ┌──────┴──────┐                           │
│                    │ WirePlumber │                           │
│                    │ (session    │                           │
│                    │  manager)   │                           │
│                    └──────┬──────┘                           │
│                           │  policy decisions:              │
│                           │  routing, defaults,             │
│                           │  device profiles                │
├───────────────────────────┼─────────────────────────────────┤
│          Kernel           │                                 │
│                    ┌──────┴──────┐                           │
│                    │    ALSA     │                           │
│                    │ (drivers)   │                           │
│                    └──────┬──────┘                           │
│                           │                                 │
│              ┌────────────┼────────────┐                    │
│              │            │            │                    │
│        snd-usb-audio  snd-hda-intel  snd-hda-intel         │
│        (USB devices)  (HDMI audio)   (onboard codec)       │
├───────────────────────────┼─────────────────────────────────┤
│         Hardware          │                                 │
│              ┌────────────┼────────────┐                    │
│              │            │            │                    │
│          Audient       AMD GPU      Realtek ALC             │
│           EVO4         HDMI out     (headphone/line)        │
└─────────────────────────────────────────────────────────────┘
```

### Audio ↔ Video Parallel

The audio and video stacks on modern Linux (Wayland) share a similar
layered architecture:

| Layer | Audio | Video |
|-------|-------|-------|
| **Hardware** | Sound card, USB interface | GPU, display |
| **Kernel driver** | ALSA (`snd-*`) | DRM/KMS (`amdgpu`, `i915`) |
| **Userspace server** | PipeWire (mixes audio, routes streams) | Wayland compositor (composites windows, routes input) |
| **Policy/session** | WirePlumber (which app → which output) | Window manager rules (which window → which workspace) |
| **App API** | PulseAudio / JACK / PipeWire | Wayland protocol / XWayland |
| **Compat layer** | `pipewire-pulse` (for PA apps) | XWayland (for X11 apps) |

Key insight: **PipeWire is to audio what Hyprland is to video** — it
multiplexes hardware access so multiple clients can share devices. Without
it, only one app can use a sound card at a time (just like raw DRM gives
exclusive GPU access).

### ALSA (Advanced Linux Sound Architecture)

Kernel-level. Provides:
- `/dev/snd/pcmC0D0p` — PCM playback device (card 0, device 0)
- `/dev/snd/controlC0` — mixer controls (volume, mute)
- One client at a time per PCM device (no mixing)

ALSA alone is like direct DRM access — fast but exclusive. You need a
userspace server (PipeWire) to share.

### PipeWire

Userspace daemon that replaces both PulseAudio and JACK. Core concepts:

- **Graph**: directed graph of nodes connected by links
- **Node**: a processing unit (ALSA device, application stream, filter)
- **Port**: input or output on a node (one per channel)
- **Link**: connection between an output port and an input port

PipeWire handles: mixing multiple streams, sample rate conversion,
format conversion, latency compensation, and buffer management.

### WirePlumber

Session manager — the policy engine. Decides:
- Which device profile to activate (stereo? surround? pro-audio?)
- Which app connects to which sink/source
- Default devices
- Device-specific rules (channel maps, sample rates)

Config lives in `~/.config/wireplumber/wireplumber.conf.d/*.conf` (SPA-JSON
format). **Note:** WirePlumber 0.5+ dropped Lua config support.

### PulseAudio Compatibility

`pipewire-pulse` provides the PulseAudio socket (`/run/user/1000/pulse/`),
so tools like `pactl`, `pavucontrol`, and all PulseAudio-native apps work
transparently. From the app's perspective, PipeWire *is* PulseAudio.

## How the EVO4 Fits In

The EVO4 is a USB Audio Class 2 (UAC2) device with 4 USB interfaces:

```
Audient EVO4 (USB, bus 003)
│
├── Interface 0 — Audio Control
│   UAC2 descriptors: feature units, extension units, mixer unit
│   Defines the device topology (what controls exist)
│
├── Interface 1 — Audio Streaming (playback)
│   4 channels: FL FR FC LFE
│   Formats: S32_LE (24-bit) or S16_LE
│   Rates: 44100, 48000, 88200, 96000 Hz
│   Endpoint: 0x01 OUT (async, with feedback EP 0x81)
│
├── Interface 2 — Audio Streaming (capture)
│   4 channels: FL FR FC LFE
│   Same formats and rates as playback
│   Endpoint: 0x82 IN (async)
│
└── Interface 3 — DFU (Device Firmware Update)
    Not used for audio. Claimed by evo4_raw kernel module
    to get a USB device handle for control transfers.
```

**Driver ownership:**

```
snd-usb-audio ──► iface 0, 1, 2 ──► ALSA card "EVO4" (card 0)
                                      ├── pcmC0D0p (playback, 4ch)
                                      └── pcmC0D0c (capture, 4ch)

evo4_raw ────────► iface 3 ──────────► /dev/evo4 (misc device)
                                        └── ioctl for USB control transfers
```

**PipeWire sees two ALSA nodes:**
- `alsa_output.usb-Audient_EVO4-00.analog-surround-40` — 4ch sink
- `alsa_input.usb-Audient_EVO4-00.analog-surround-40` — 4ch source

### The 4-Channel Problem

The EVO4 reports 4 channels (FL FR FC LFE) but physically has only 2
outputs and 2 inputs. Channels 3-4 (FC, LFE) are internal to the device
and ignored.

When an app sends stereo audio to a surround 4.0 sink, PipeWire upmixes
it — spreading audio across 4 channels. The result: audio plays only on
FL+FR at reduced volume, or channel mapping goes wrong entirely.

Similarly, the 4ch capture includes 2 real mic inputs (FL, FR) and 2
unused channels. Apps expecting stereo get confused.

**Solution:** loopback modules that present clean stereo nodes.

## The Loopback Solution (Current Config)

### Playback Path

```
Application (stereo: FL, FR)
    │
    ▼
┌───────────────────────────┐
│ evo4_stereo_output        │  PipeWire loopback sink
│ (2ch: FL, FR)             │  Capture side: apps connect here
│                           │
│ Playback side:            │
│ (4ch: FL, FR, FL, FR)     │  Duplicates L/R to fill 4 channels
│ target: alsa_output...    │  stream.dont-remix = true
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ alsa_output.usb-Audient   │  Raw ALSA 4ch surround sink
│ _EVO4-00.analog-surround  │
│ -40                       │  Hardware only uses FL+FR
└───────────┬───────────────┘
            │
            ▼
      EVO4 speakers/headphones
```

### Capture Path

```
      EVO4 microphone inputs
            │
            ▼
┌───────────────────────────┐
│ alsa_input.usb-Audient    │  Raw ALSA 4ch surround source
│ _EVO4-00.analog-surround  │
│ -40                       │  4ch: FL, FR, RL, RR
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐
│ evo4_stereo_mic           │  PipeWire loopback source
│                           │
│ Capture side:             │
│ (4ch: FL, FR, RL, RR)     │  stream.dont-remix = true
│ target: alsa_input...     │
│                           │
│ Playback side:            │
│ (2ch: FL, FR)             │  Apps see clean stereo mic
└───────────┬───────────────┘
            │
            ▼
      Application (stereo mic input)
```

### Config Files

| File | Purpose | Status |
|------|---------|--------|
| `~/.config/pipewire/pipewire.conf.d/evo4-stereo.conf` | Loopback modules (stereo output + mic) and a virtual null sink | **Working** (null sink is unused) |
| `~/.config/pipewire/pipewire.conf.d/evo4-alsa-profiles.conf` | ALSA profile overrides, references custom profile set | **Partially broken** (profile set doesn't exist) |
| `~/.config/pipewire/pipewire-pulse.conf.d/evo4-defaults.conf` | Sets PA default sink/source to loopback nodes | **Working** |
| `~/.config/wireplumber/main.lua.d/51-evo4-config.lua` | WP rules: force stereo, pro-audio profile | **Dead code** (WP 0.5+ ignores Lua) |
| `~/.config/wireplumber/wireplumber.conf.d/alsa-soft-mixer.conf` | Forces software volume on all ALSA devices | **Working** |
| `~/.local/bin/evo4-setup.sh` | Detects EVO4, sets pro-audio profile, sets defaults via pactl | **Working** |
| `~/.config/systemd/user/evo4-setup.service` | Runs evo4-setup.sh after PipeWire starts | **Broken** (wrong path: `/home/sasha/`) |

## Control Plane vs Data Plane

The EVO4 has two independent control paths:

```
┌─────────────────────────────────────────────────────────────┐
│                    CONTROL PLANE                            │
│                                                             │
│  ┌─────────────────────────────────────────────────┐        │
│  │  evoctl.py → evo4_raw.ko → USB endpoint 0      │        │
│  │                                                 │        │
│  │  Controls: output volume (-96..0 dB)            │        │
│  │            input gain (-8..+50 dB)              │        │
│  │            monitor mix (input↔playback ratio)   │        │
│  │            input/output mute                    │        │
│  │            phantom 48V power                    │        │
│  │                                                 │        │
│  │  These are HARDWARE controls — they adjust the  │        │
│  │  analog signal path inside the EVO4.            │        │
│  └─────────────────────────────────────────────────┘        │
│                                                             │
│  ┌─────────────────────────────────────────────────┐        │
│  │  WirePlumber → PipeWire → ALSA mixer            │        │
│  │                                                 │        │
│  │  Controls: routing (which app → which output)   │        │
│  │            software volume (digital gain)       │        │
│  │            device profile (surround/stereo/pro) │        │
│  │            sample rate, buffer size              │        │
│  │                                                 │        │
│  │  These are SOFTWARE controls — they adjust the  │        │
│  │  digital signal before it reaches the device.   │        │
│  └─────────────────────────────────────────────────┘        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                      DATA PLANE                             │
│                                                             │
│  App → PipeWire graph → ALSA PCM → snd-usb-audio           │
│        (mix, resample)   (iface 1/2)   → USB isochronous   │
│                                          transfers          │
│                                                             │
│  Audio samples flow continuously through the data plane.    │
│  Control plane changes take effect without interrupting     │
│  the stream.                                                │
└─────────────────────────────────────────────────────────────┘
```

**Why both?** PipeWire's software volume applies digital gain before the
DAC — it reduces bit depth. The EVO4's hardware volume (controlled by
evoctl) adjusts the analog output stage — it preserves full bit depth.
For best audio quality, keep PipeWire volume at 100% and use evoctl for
volume control.

## This Machine's Audio Devices

**ALSA cards** (`/proc/asound/cards`):

| Card | Driver | Device |
|------|--------|--------|
| 0 | snd-usb-audio | Audient EVO4 (USB) |
| 1 | snd-hda-intel | HDA ATI HDMI (AMD GPU HDMI out) |
| 2 | snd-hda-intel | HD-Audio Generic (Realtek ALC, onboard) |
| 3 | snd-hda-intel | HD-Audio Generic (Radeon HDMI) |

**PipeWire sinks** (outputs):

| ID | Name | Channels | Notes |
|----|------|----------|-------|
| 115 | EVO4 Analog Surround 4.0 | 4ch | Raw ALSA node, default sink |
| 40 | evo4_stereo_output | 2ch | Loopback virtual sink |
| 74 | Navi 21/23 HDMI | 2ch | GPU HDMI |
| 81 | Ryzen HD Audio Analog Stereo | 2ch | Onboard headphone/line |

**PipeWire sources** (inputs):

| ID | Name | Channels | Notes |
|----|------|----------|-------|
| 97 | EVO4 Analog Surround 4.0 | 4ch | Raw ALSA node |
| 41 | evo4_stereo_mic | 2ch | Loopback virtual source, default |
| 82 | Ryzen HD Audio Analog Stereo | 2ch | Onboard mic |

**Current defaults:**
- Sink: `bluez_output.94_DB_56_03_22_98.1` (Bluetooth, likely disconnected — falls back to EVO4)
- Source: `evo4_stereo_mic`

## Glossary

- **ALSA** — Advanced Linux Sound Architecture. Kernel-level audio subsystem.
- **PCM** — Pulse-Code Modulation. Digital audio data (samples).
- **UAC2** — USB Audio Class 2. Standard protocol for USB audio devices.
- **PipeWire graph** — The directed graph of nodes and links that audio flows through.
- **Node** — A processing unit in PipeWire (device, stream, filter, loopback).
- **Port** — An input or output on a node, one per audio channel.
- **Link** — Connection between an output port and input port.
- **WirePlumber** — PipeWire's session manager. Handles policy and routing.
- **Loopback module** — PipeWire module that creates a virtual sink/source pair, forwarding audio between them. Used for channel remapping.
- **Pro-audio profile** — ALSA card profile that exposes raw PCM channels as individual ports (AUX0-N) instead of named surround channels.
- **ACP** — ALSA Card Profiles. PipeWire's system for mapping ALSA devices to PipeWire nodes with appropriate channel layouts.
- **SPA** — Simple Plugin API. PipeWire's plugin system; SPA-JSON is the config format used by PipeWire and WirePlumber 0.5+.
