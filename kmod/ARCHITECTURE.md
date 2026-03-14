# evo4_raw Kernel Module — Architecture

## Problem

The Audient EVO4 exposes its mixer controls (volume, gain, mute, monitor mix)
through USB Audio Class control transfers on endpoint 0. On Linux,
`snd-usb-audio` claims the audio interfaces (0-2) and the usbfs layer blocks
userspace from sending control transfers to a device whose interfaces are
kernel-owned. There is no way to send vendor-specific or mixer-unit control
transfers from userspace while `snd-usb-audio` is active.

## Solution

`evo4_raw` is a minimal out-of-tree kernel module that:

1. Binds to **interface 3** (DFU, left unclaimed by `snd-usb-audio`)
2. Uses that binding solely to obtain a `usb_device` handle
3. Exposes `/dev/evo4` as a misc device with a single ioctl
4. Forwards arbitrary USB control transfers through `usb_control_msg()`

This works because `usb_control_msg()` operates on endpoint 0 (the default
control pipe), which is device-global — it doesn't belong to any interface.
The module never touches audio interfaces, so `snd-usb-audio` continues
streaming audio undisturbed.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Userspace                            │
│                                                             │
│  ┌──────────┐     ┌──────────────┐     ┌────────────────┐  │
│  │audient.py│────▶│evo4_alsa.py  │────▶│  evo4_kmod.py  │  │
│  │  (CLI)   │     │(EVO4Controller)    │(ioctl wrapper) │  │
│  └──────────┘     └──────────────┘     └───────┬────────┘  │
│                                                │            │
│                                    ioctl(fd, EVO4_CTRL_TRANSFER, buf)
│                                                │            │
├────────────────────────────────────────────────┼────────────┤
│                        Kernel                  │            │
│                                                ▼            │
│                                        ┌──────────────┐    │
│                                        │  /dev/evo4   │    │
│                                        │  (misc dev)  │    │
│                                        └──────┬───────┘    │
│                                               │             │
│                                               ▼             │
│                                     ┌───────────────────┐  │
│                                     │    evo4_raw.ko    │  │
│                                     │  (this module)    │  │
│  ┌────────────────┐                 │                   │  │
│  │ snd-usb-audio  │                 │ usb_control_msg() │  │
│  │ (interfaces    │                 │ on endpoint 0     │  │
│  │  0, 1, 2)      │                 │                   │  │
│  └───────┬────────┘                 └─────────┬─────────┘  │
│          │                                    │             │
│          │  claims iface 0-2       claims iface 3 (DFU)    │
│          │                                    │             │
├──────────┼────────────────────────────────────┼─────────────┤
│          │            USB Bus                 │             │
│          ▼                                    ▼             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Audient EVO4 (USB Device)               │   │
│  │                                                      │   │
│  │  Endpoint 0 (Control) ◄─── all control transfers     │   │
│  │  Interface 0 ─── Audio Control (UAC2 descriptors)    │   │
│  │  Interface 1 ─── Audio Streaming (playback)          │   │
│  │  Interface 2 ─── Audio Streaming (capture)           │   │
│  │  Interface 3 ─── DFU (firmware update, unused)       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## ioctl Protocol

A single ioctl command `EVO4_CTRL_TRANSFER` carries all communication.
The userspace struct matches the kernel struct byte-for-byte:

```
struct evo4_ctrl_xfer (264 bytes, little-endian):
┌───────────────┬──────┬──────────────────────────────────────┐
│ Field         │ Size │ Description                          │
├───────────────┼──────┼──────────────────────────────────────┤
│ bRequestType  │ u8   │ USB bmRequestType                    │
│ bRequest      │ u8   │ USB bRequest (e.g. SET_CUR=0x01)     │
│ wValue        │ u16  │ (ControlSelector << 8) | ChannelNum  │
│ wIndex        │ u16  │ (EntityID << 8) | Interface          │
│ wLength       │ u16  │ Data length (max 256)                │
│ data          │ u8[256] │ Transfer payload                  │
└───────────────┴──────┴──────────────────────────────────────┘
```

The ioctl number is `_IOWR('E', 0, struct evo4_ctrl_xfer)`:
- Direction: read+write (3)
- Type: 'E' (0x45)
- Number: 0
- Size: 264

## Data Flow

### SET (host → device)

```
Python                    Kernel Module              EVO4
  │                           │                        │
  │  ioctl(SET_CUR data)      │                        │
  ├──────────────────────────▶│                        │
  │                           │  usb_control_msg()     │
  │                           │  (OUT on endpoint 0)   │
  │                           ├───────────────────────▶│
  │                           │                        │ applies setting
  │       return 0            │       ACK              │
  │◀──────────────────────────│◀───────────────────────│
```

### GET (device → host)

```
Python                    Kernel Module              EVO4
  │                           │                        │
  │  ioctl(GET_CUR, len=N)    │                        │
  ├──────────────────────────▶│                        │
  │                           │  usb_control_msg()     │
  │                           │  (IN on endpoint 0)    │
  │                           ├───────────────────────▶│
  │                           │    N bytes response    │
  │                           │◀───────────────────────│
  │  ioctl returns with       │                        │
  │  data[] + wLength filled  │                        │
  │◀──────────────────────────│                        │
```

## USB Entities Used

| Entity | Type | wIndex | Purpose |
|--------|------|--------|---------|
| Feature Unit 10 | UAC2 FU | `0x0A00` | Output volume (-96..0 dB) |
| Feature Unit 11 | UAC2 FU | `0x0B00` | Input gain (-8..+50 dB) |
| Extension Unit 56 | Vendor | `0x3800` | Monitor mix (0..127) |
| Extension Unit 58 | Vendor | `0x3A00` | Input mute (per-channel) |
| Extension Unit 59 | Vendor | `0x3B00` | Output mute |

## Module Lifecycle

```
USB plug-in
    │
    ▼
evo4_probe() ── only accepts interface 3
    │
    ├── kzalloc evo4_device
    ├── usb_get_dev (ref-count the usb_device)
    ├── misc_register → creates /dev/evo4
    └── stores global evo4_dev pointer

ioctl call
    │
    ▼
evo4_ioctl()
    │
    ├── copy_from_user (get struct from userspace)
    ├── kmalloc DMA buffer
    ├── mutex_lock (serialize access)
    ├── usb_control_msg (send/receive on endpoint 0)
    ├── mutex_unlock
    ├── copy_to_user (return data for IN transfers)
    └── kfree DMA buffer

USB unplug
    │
    ▼
evo4_disconnect()
    │
    ├── mutex_lock
    ├── misc_deregister (removes /dev/evo4)
    ├── usb_put_dev (release ref)
    ├── NULL out evo4_dev
    ├── mutex_unlock
    └── kfree
```

## Safety

- **Mutex**: `evo4_lock` serializes all ioctl calls and protects against
  concurrent disconnect.
- **DMA buffer**: Stack memory can't be used for USB transfers; the module
  kmallocs a buffer for each transfer.
- **Device check**: Every ioctl verifies `evo4_dev` and `evo4_dev->udev` are
  non-NULL under the lock, returning `-ENODEV` if the device was unplugged.
- **Size limit**: `wLength` is capped at 256 bytes (`EVO4_MAX_DATA`).

## Files

| File | Role |
|------|------|
| `kmod/evo4_raw.c` | Kernel module source |
| `kmod/Makefile` | Standard out-of-tree kbuild |
| `kmod/dkms.conf` | DKMS config for auto-rebuild on kernel upgrades |
| `kmod/99-evo4.rules` | udev rule: `/dev/evo4` owned by `dialout` group |
| `kmod/install.sh` | Install script (DKMS + udev + modprobe) |
| `kmod/uninstall.sh` | Uninstall script |
| `evo4_kmod.py` | Python ioctl wrapper (userspace side) |
