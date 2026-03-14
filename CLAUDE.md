# CLAUDE.md

## Project goals

- Linux-only Python control script for Audient EVO 4 sound mixer that:
  - allows device control and settings polling using USB control transfers via kernel module
  - does not interrupt ongoing audio transmission (coexists with snd-usb-audio)
- For functionality and overall project details read @./README.md

## Running the script

```bash
# Linux — requires evo4_raw kernel module loaded
# Example: set volume (0-100)
python audient.py set volume 75

# Get current state
python audient.py get volume
python audient.py get mute -t output
python audient.py set mix 50
```

## Architecture

- `audient.py` — CLI entry point with get/set subcommands
- `evo4_alsa.py` — `EVO4Controller` class, all controls via kernel module ioctl
- `evo4_kmod.py` — Python wrapper for `/dev/evo4` ioctl (raw USB control transfers)
- `kmod/evo4_raw.c` — out-of-tree kernel module that coexists with snd-usb-audio
- See `FINDINGS.md` for USB protocol details and `PLAN.md` for design rationale
