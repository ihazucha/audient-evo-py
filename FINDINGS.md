# Audient EVO4 — USB Control Findings

## Working Control Stack

### ALSA (via snd-usb-audio, no audio disruption)
- **Volume** — FU10, ALSA name `"EVO4 "`, 4ch but only CH1-2 respond
- **Gain** — FU11, ALSA name `"Mic"`, 4ch but only CH1-2 respond
- **Mute** — EU59, ALSA name `"Extension Unit"`, boolean

### Kernel Module (evo4_raw.ko, no audio disruption)
- **Monitor Mix** — EU56 CS=0 CN=0, wIndex=`0x3800`, wValue=`0x0000`
  - Range: 0–127 (0=full input, 127=full playback, linear)
  - 2-byte little-endian read/write
  - Not exposed by snd-usb-audio; only accessible via kmod

## Kernel Module Details

- Binds to interface 3 (DFU, unbound by snd-usb-audio) to get usb_device handle
- Sends control transfers via `usb_control_msg()` on endpoint 0 (control pipe)
- Data buffer must be `kmalloc`'d (not stack) for DMA — initial version had this bug
- `/dev/evo4` misc device, ioctl `EVO4_CTRL_TRANSFER`

## USB Topology

```
Interfaces:
  0: Audio Control (snd-usb-audio) — EP3 IN (Interrupt)
  1: Audio Streaming OUT (playback) — EP1 OUT (Isoch Async) + Feedback
  2: Audio Streaming IN (capture) — EP2 IN (Isoch Async)
  3: DFU (firmware update) — unbound, used by evo4_raw.ko

Signal Path:
  IT1 (Mic, 4ch) → FU11 (gain) ──┐
                                   ├→ EU50 → MU60 ("Mix 1", 2ch out)
  IT2 (USB, 4ch) → FU10 (vol) ───┘          │
                                   EU56 ─────┘
                                     ↓
                                   EU58 → EU59 → OT20 (Speaker)
```

## Probe Results (all units)

wIndex = `(EntityID << 8) | Interface(0)`
wValue = `(CS << 8) | CN`
All values 2-byte little-endian.

### FU10 — Output Volume (wIndex=0x0A00)

| CS | Function | CH1 | CH2 | CH3 | CH4 | Notes |
|----|----------|-----|-----|-----|-----|-------|
| 1 | Mute | 0xBB00 | 0xBB00 | 0xBB00 | 0xBB00 | Per-channel mute |
| 2 | Volume | 0x0000 (0 dB) | 0x0000 (0 dB) | 0x8080 (-127.5 dB) | 0x8080 (-127.5 dB) | CH1-2 active, CH3-4 fixed |

- Volume range: -127.00..0.00 dB (UAC2 16-bit signed, 1/256 dB steps)
- Only CH1-2 respond to changes (physical knob + ALSA + kmod)

### FU11 — Input Gain (wIndex=0x0B00)

| CS | Function | CH1 | CH2 | CH3 | CH4 | Notes |
|----|----------|-----|-----|-----|-----|-------|
| 1 | Mute | 0x0080 | 0x0080 | 0x0080 | 0x0080 | Per-channel mute |
| 2 | Volume | varies | varies | 0x00F8 (-8 dB) | 0x00F8 (-8 dB) | CH1-2 active, CH3-4 fixed at -8 dB |

- Gain range: -8.00..+50.00 dB
- CH1 = input 1, CH2 = input 2, CH3-4 fixed

### EU50 (wIndex=0x3200)
- All STALLs. No valid controls found.

### EU56 — Monitor Mix (wIndex=0x3800) ✅ CONFIRMED
| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0 | 0x007F (127) | **Monitor mix ratio** — 0=input, 127=playback |
| 0 | 1-4 | 0x007F | Same value (global, not per-channel) |
| 1 | 0-4 | 0x0032 (50) | Unknown — secondary param? |
| 2-7 | 0-4 | 0x0000 | Zeros |

**WARNING:** Probing higher CS values on EU56 can put it into an error state
requiring USB re-plug to recover. Only use CS=0 CN=0 for mix control.

### EU57 (wIndex=0x3900)
- All STALLs. No valid controls found.

### EU58 — Unknown Config (wIndex=0x3A00) ⬅ TODO
| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0-4 | 0x0000 | Unknown |
| 1 | 0 | 0x00F8 (-8 dB?) | Mirrors FU11 gain default? |
| 1 | 1 | 0x0032 (50) | Mirrors FU11 gain ch2? |
| 1 | 2-4 | 0x00F8 | Same as CN=0 |
| 2-4 | 0-4 | 0x0000 | Zeros |
| 5 | 1 | 0xFFFF | Flag/boolean? |
| 5 | 0,2-4 | 0x0000 | |
| 6 | 0-4 | 0x0000 | Zeros |
| 7 | 0-1 | 0x0003 | Unknown config |
| 7 | 2-4 | 0x0000 | |

Likely candidates: **input select, phantom power, or other hardware config.**
Needs SET_CUR experiments to identify.

### EU59 — Mute / Output Config (wIndex=0x3B00)
| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0-1 | 0x0000 | Unknown |
| 0 | 2-4 | 0x8080 | Mirrors FU10 ch3-4 mute? |
| 1 | 0-4 | 0x0000 | **Mute control** (ALSA-exposed) |
| 2 | 0-1 | 0x0100 | Unknown |
| 2 | 2-4 | 0x0000 | |

### MU60 — Mixer Unit (wIndex=0x3C00)
- All STALLs. Firmware does not implement standard UAC2 mixer controls.
- The actual mixing is controlled via EU56, not MU60.

## Known Issues

1. **Aggressive probing breaks EU56** — sending GET_CUR to invalid CS/CN
   combinations on EU56 puts it in an error state. Only recoverable by USB
   re-plug. Stick to known-good CS=0 CN=0 for mix control.

2. **CH3-4 unresponsive** — both FU10 and FU11 channels 3-4 are fixed at
   their default values and don't respond to SET_CUR. Likely internal
   routing channels not meant for user control.

3. **pyalsaaudio setvolume quirk** — `setvolume(pct)` without channel arg
   only sets CH0-1. Must loop `for ch in range(4): setvolume(pct, ch)`.

## File Layout

```
├── audient.py          # CLI entry point (platform dispatch)
├── evo4_alsa.py        # Linux backend: ALSA + kmod for mix
├── evo4_usb.py         # Windows backend: pyusb
├── evo4_kmod.py        # Python ioctl wrapper for /dev/evo4
├── kmod/
│   ├── evo4_raw.c      # Kernel module (~150 LOC)
│   ├── Makefile
│   ├── dkms.conf
│   └── 99-evo4.rules   # Udev rule (audio group access)
├── probe_mu60.py       # Unit discovery probe (aggressive, can break EU56)
├── probe_set.py        # EU56 mix SET/GET test
├── probe_volume.py     # FU10/FU11 volume/gain probe
├── FINDINGS.md         # This file
└── PLAN.md             # Implementation plan
```
