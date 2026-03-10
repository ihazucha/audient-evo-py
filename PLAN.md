# Implementation Plan: EVO4 Kernel Module for Raw USB Control

## Goal

Build a small out-of-tree kernel module (`evo4_raw`) that:
- Binds to the EVO4 device alongside snd-usb-audio (not replacing it)
- Exposes `/dev/evo4` as a misc device
- Accepts ioctl calls to send/receive arbitrary USB control transfers
- Lets our Python script control Mixer Unit 60 (and any other unexposed unit)

## Why a Kernel Module?

The Linux kernel blocks userspace (usbfs) from sending class-specific USB
control transfers (`bmRequestType=0x21/0xa1`) to interfaces owned by a kernel
driver. snd-usb-audio owns interface 0 (Audio Control). The kernel's internal
`usb_control_msg()` has no such restriction — it talks directly to the USB host
controller. A module that calls this function can coexist with snd-usb-audio.

## Architecture

```
  Python (audient.py)
       │  ioctl(/dev/evo4, EVO4_CTRL_TRANSFER, {setup + data})
       ▼
  evo4_raw.ko (misc device, /dev/evo4)
       │  usb_control_msg(udev, ...)
       ▼
  USB Host Controller → EVO4 hardware
       ▲
  snd-usb-audio (untouched, handles audio + ALSA mixer)
```

## Steps

### Step 1: Kernel Module (`kmod/evo4_raw.c`)

~120 lines of C. Key components:

- **USB ID table**: Match VID=0x2708, PID=0x0006
- **`usb_driver` probe/disconnect**: Get `struct usb_device*`, register misc device
- **Misc device**: `/dev/evo4`, single file_operations with `unlocked_ioctl`
- **ioctl interface**: One ioctl command `EVO4_CTRL_TRANSFER` that takes:
  ```c
  struct evo4_ctrl_xfer {
      __u8  bRequestType;   // direction | type | recipient
      __u8  bRequest;       // e.g. 0x01 (CUR)
      __u16 wValue;         // (CS << 8) | CN
      __u16 wIndex;         // (EntityID << 8) | Interface
      __u16 wLength;        // data size
      __u8  data[256];      // payload (in/out)
  };
  ```
- **Implementation**: Calls `usb_control_msg()` with the user-provided parameters
- **Safety**: Validate wLength ≤ 256, check USB direction bit matches ioctl direction

### Step 2: Makefile & DKMS

- `kmod/Makefile` — standard out-of-tree module Makefile
- `kmod/dkms.conf` — for optional DKMS install (auto-rebuild on kernel update)
- Build: `cd kmod && make` → produces `evo4_raw.ko`
- Load: `sudo insmod evo4_raw.ko` (or `modprobe` after DKMS install)
- Udev rule: `99-evo4.rules` — set `/dev/evo4` permissions so non-root can use it

### Step 3: Python Integration (`evo4_kmod.py`)

Small Python wrapper using `fcntl.ioctl()` + `struct` to pack/unpack the
`evo4_ctrl_xfer` struct:

```python
import fcntl, struct

EVO4_CTRL_TRANSFER = 0xC108E500  # _IOWR('E', 0, struct evo4_ctrl_xfer)

def ctrl_transfer(fd, bmRequestType, bRequest, wValue, wIndex, data=b'', length=0):
    buf = struct.pack('<BBHHH', bmRequestType, bRequest, wValue, wIndex, length)
    buf += data.ljust(256, b'\x00')
    result = fcntl.ioctl(fd, EVO4_CTRL_TRANSFER, buf)
    return result  # contains response data for GET requests
```

### Step 4: Update `evo4_alsa.py`

Replace the mix workaround with real MU60 control:
- Keep ALSA for volume/gain/mute (works perfectly)
- Use `/dev/evo4` + ioctl for `get_mix()` / `set_mix()` targeting Mixer Unit 60
- Graceful fallback: if `/dev/evo4` not available, warn and use the old workaround

### Step 5: Discover MU60 Protocol

The exact wValue/data format for Mixer Unit 60 coefficients is unknown. Options:
1. **USB capture on Windows**: Run EVO4 app, change monitor mix, capture with USBPcap
2. **Probe from Linux**: With the kernel module loaded, try GET_CUR on
   wIndex=0x3C00 with various wValue combinations (channel/selector pairs)
3. **UAC2 spec reference**: MU60 should follow USB Audio Class 2.0 Mixer Unit
   control semantics — coefficients addressed by input/output channel pair

This step may require iteration. The kernel module makes probing easy — just
call ioctl with different parameters and observe responses.

## File Layout (after implementation)

```
audient-evo-py/
├── audient.py          # CLI entry point
├── evo4_alsa.py        # Linux ALSA backend (vol/gain/mute)
├── evo4_usb.py         # Windows pyusb backend
├── evo4_kmod.py        # Python wrapper for /dev/evo4 ioctl
├── kmod/
│   ├── evo4_raw.c      # Kernel module source
│   ├── Makefile         # Out-of-tree build
│   ├── dkms.conf        # Optional DKMS config
│   └── 99-evo4.rules   # Udev permissions rule
├── FINDINGS.md
├── PLAN.md
└── README.md
```

## Risk & Mitigations

| Risk | Mitigation |
|------|------------|
| Module crashes kernel | Validate all ioctl inputs; limit data size to 256B |
| Conflicts with snd-usb-audio | Module doesn't claim any interface; only calls usb_control_msg on device level |
| Kernel version compat | Use stable USB core APIs only; DKMS handles rebuilds |
| Security (arbitrary USB control) | Restrict to EVO4 VID/PID only; udev rule limits access |
