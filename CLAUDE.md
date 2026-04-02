# CLAUDE.md

## Project

Linux Python controller for Audient EVO 4.
Uses a custom kernel module (`evo4_raw`) to send USB control transfers
alongside `snd-usb-audio`. See [README.md](README.md) for usage and
[DESIGN.md](DESIGN.md) for architecture and protocol details.

## Running

```bash
python evoctl.py set volume 75
python evoctl.py get volume
python evoctl.py set monitor 50
python evoctl.py get mute -t output
```

Requires `evo4_raw` kernel module loaded (`/dev/evo4` must exist).

## Structure

- `evoctl.py` — CLI (argparse, get/set subcommands)
- `evo4/controller.py` — `EVO4Controller` class, all controls via kmod ioctl
- `evo4/kmod.py` — Python ioctl wrapper for `/dev/evo4`
- `kmod/evo4_raw.c` — out-of-tree kernel module (~180 LOC)
- `dev/` — reverse-engineered probe tools and raw findings
- `tests/` — unit and integration tests
- `tui/` - CLI user interface

## Testing

```bash
pytest tests/test_kmod.py          # unit tests (no hardware)
pytest tests/test_controller.py    # integration tests (requires connected EVO4)
```
