# Design — Audient EVO4 Linux Controller

## Problem

The Audient EVO4 exposes its mixer controls (volume, gain, mute, monitor mix)
through USB control transfers on endpoint 0. On Linux, `snd-usb-audio` claims
the audio interfaces and the usbfs layer blocks userspace from sending control
transfers to a kernel-owned device. The vendor control app is Windows/macOS
only.

## Solution

`evo4_raw` is a minimal out-of-tree kernel module that:

1. Binds to **interface 3** (DFU, left unclaimed by `snd-usb-audio`)
2. Uses that binding solely to obtain a `usb_device` handle
3. Exposes `/dev/evo4` as a misc device with a single ioctl
4. Forwards USB control transfers through `usb_control_msg()`

This works because `usb_control_msg()` operates on endpoint 0 (the default
control pipe), which is device-global. The module never touches audio
interfaces, so `snd-usb-audio` continues streaming undisturbed.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Userspace                           │
│                                                          │
│ ┌──────────┐     ┌────────────────┐     ┌──────────────┐ │
│ │evoctl.py │────▶│controller.py   │────▶│kmod.py       │ │
│ │(CLI)     │     │(EVO4Controller)│     │(ioctl wrapper) │
│ └──────────┘     └────────────────┘     └──────┬───────┘ │
│                                              │           │
│                                  ioctl(fd, EVO4_CTRL_TRANSFER, buf)
│                                              │           │
├──────────────────────────────────────────────┼───────────┤
│                      Kernel                  │           │
│                                              ▼           │
│                                      ┌──────────────┐    │
│                                      │  /dev/evo4   │    │
│                                      │  (misc dev)  │    │
│                                      └──────┬───────┘    │
│                                             │            │
│                                             ▼            │
│                                   ┌───────────────────┐  │
│                                   │    evo4_raw.ko    │  │
│ ┌────────────────┐                │ usb_control_msg() │  │
│ │ snd-usb-audio  │                │ on endpoint 0     │  │
│ │ (iface 0-2)    │                └─────────┬─────────┘  │
│ └───────┬────────┘                          │            │
│         │  claims iface 0-2      claims iface 3 (DFU)    │
├─────────┼───────────────────────────────────┼────────────┤
│         ▼              USB Bus              ▼            │
│ ┌───────────────────────────────────────────────────┐    │
│ │              Audient EVO4 (USB Device)            │    │
│ │  Endpoint 0 (Control) ◄── all control transfers   │    │
│ │  Interface 0 — Audio Control (UAC2 descriptors)   │    │
│ │  Interface 1 — Audio Streaming (playback)         │    │
│ │  Interface 2 — Audio Streaming (capture)          │    │
│ │  Interface 3 — DFU (unused, bound by evo4_raw)    │    │
│ └───────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

## ioctl Protocol

A single ioctl command `EVO4_CTRL_TRANSFER` carries all communication.
The struct is identical in kernel and userspace (264 bytes, little-endian):

| Field | Size | Description |
|-------|------|-------------|
| bRequestType | u8 | USB bmRequestType (0x21=SET, 0xA1=GET) |
| bRequest | u8 | USB bRequest (0x01 = CUR) |
| wValue | u16 | (ControlSelector << 8) \| ChannelNumber |
| wIndex | u16 | (EntityID << 8) \| InterfaceNumber |
| wLength | u16 | Data length (max 256) |
| data | u8[256] | Transfer payload |

ioctl number: `_IOWR('E', 0, struct evo4_ctrl_xfer)` — read+write, type 'E',
number 0, size 264.

## Supported Controls

| Entity | wIndex | Function | Range | Notes |
|--------|--------|----------|-------|-------|
| Feature Unit 10 | `0x0A00` | Output volume | -127..0 dB | CS=2, 2 channels |
| Feature Unit 11 | `0x0B00` | Input gain | -8..+50 dB | CS=2, 2 channels |
| Extension Unit 56 | `0x3800` | Monitor mix | 0..127 | CS=0 CN=0 only |
| Extension Unit 58 | `0x3A00` | Phantom 48V | 0/1 (4 bytes) | CS=0, per-channel |
| Extension Unit 58 | `0x3A00` | Input mute | 0/1 (4 bytes) | CS=2, per-channel |
| Extension Unit 59 | `0x3B00` | Output mute | 0/1 (4 bytes) | CS=1 CN=0 |
| Mixer Unit 60 | `0x3C00` | Loopback mixer (6×2) | -128..+8 dB | CS=1, CN=0-11, write-only |

Volume/gain use UAC2 16-bit signed values in 1/256 dB steps.
Monitor mix is linear: 0 = full input, 127 = full playback.

## Module Safety

- **Mutex** serializes all ioctl calls and protects against concurrent disconnect
- **DMA buffer**: `kmalloc`'d per transfer (stack memory can't be used for USB)
- **Device check**: every ioctl verifies device is still connected under the lock
- **Size limit**: `wLength` capped at 256 bytes

## Known Quirks

- **EU56 error state**: probing invalid CS/CN on EU56 locks the unit until
  USB re-plug. Only use CS=0 CN=0.
- **CH3-4 internal**: FU10/FU11 report 4 channels but CH3-4 are fixed at
  defaults and ignore SET_CUR.
- **Unmapped controls**: input select/mode (EU58 CS=5) is writable but its
  effect is unconfirmed. See `dev/FINDINGS.md`.
