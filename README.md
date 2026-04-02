# Audient EVO 4 - Linux Controller

Reverse-engineered Linux controller for the Audient EVO 4 USB audio interface.
Replaces the vendor's Windows/macOS-only control app. Coexists with
`snd-usb-audio` - audio streaming is never interrupted.

## Features

- **Output volume** - per-channel, power curve matching the vendor app
- **Input gain** - per-channel, linear
- **Monitor mix** - input/playback ratio
- **Mute** - per-input and output
- **Phantom power** - 48V per-input toggle
- **Loopback mixer** - MU60 6x2 matrix with per-input gain and pan

## How It Works

A small kernel module (`evo4_raw`) binds to the EVO4's unused DFU interface
to obtain a USB device handle, then exposes `/dev/evo4` for sending USB control
transfers via `usb_control_msg()` on the device-global control pipe (endpoint 0).
A Python CLI wraps the ioctl interface.

See [DESIGN.md](DESIGN.md) for architecture, protocol, and USB entity details.

## Requirements

- Linux with `snd-usb-audio` (standard kernel audio)
- Kernel headers (`linux-headers` package)
- DKMS (for auto-rebuild on kernel updates)
- Python 3.10+

## Installation

### Kernel Module

```bash
cd kmod
sudo ./install.sh
```

Installs via DKMS, adds a udev rule, and loads the module.
Users in the `dialout` group can access `/dev/evo4`.

To uninstall:

```bash
cd kmod
sudo ./uninstall.sh
```

### Python

No external dependencies. Run directly from the repo.

## Usage

```bash
# Volume (0-100)
python evoctl.py set volume 75
python evoctl.py get volume

# Volume in dB [-96, 0]
python evoctl.py set volume -20 --db
python evoctl.py get volume --db

# Gain (0-100, per-channel with -c)
python evoctl.py set gain 50 -c 1
python evoctl.py get gain

# Gain in dB [-8, 50]
python evoctl.py set gain -2 --db -c 1
python evoctl.py get gain --db

# Monitor mix (0=input, 100=playback)
python evoctl.py set monitor 50
python evoctl.py get monitor

# Mute (requires -t target)
python evoctl.py set mute on -t output
python evoctl.py get mute -t input1

# Phantom power 48V (requires -t target)
python evoctl.py set phantom on -t input1
python evoctl.py get phantom -t input1

# Loopback mixer - route mic/line inputs to loopback capture
python evoctl.py mixer input1 --volume -6 --pan 0
python evoctl.py mixer input2 --volume -6 --pan 0

# Loopback mixer - route DAW playback (main output) to loopback capture
python evoctl.py mixer output --volume -6 --pan-l -100 --pan-r 100

# Loopback mixer - route DAW playback (loopback output CH3/4) to loopback capture
python evoctl.py mixer loopback --volume -128

# Show all parameters
python evoctl.py status
```

Targets for mute: `input1`, `input2`, `output`.
Targets for phantom: `input1`, `input2`.
Mixer volume range: [-128, 8] dB (-128 = mute). Pan: -100 (left) to 100 (right).
Aliases: `g` for `get`, `s` for `set`, `m` for `mixer`.

## Project Structure

```
evoctl.py                  CLI entry point
evo4/
  controller.py            EVO4Controller - device control logic
  kmod.py                  Python ioctl wrapper for /dev/evo4
kmod/
  evo4_raw.c               Kernel module (~180 LOC)
  install.sh               DKMS install script
  uninstall.sh             Uninstall script
tests/
  test_controller.py       Integration tests (requires connected EVO4)
  test_kmod.py             Unit tests (no hardware needed)
  test_mixer_audio.py      MU60 tests - DAW/loopback routing
  test_mixer_mic.py        MU60 tests - mic/line input routing
dev/
  probe.py                 USB entity discovery/testing tool
  FINDINGS.md              Raw reverse-engineering results
```

## TODO

- Proper packaging
- Figure out how to get the project visible on GitHub
- Cross-compare with other projects:
  - https://github.com/subsubl/Evo4mixer
  - https://github.com/vijay-prema/audient-evo-linux-tools/tree/main
  - https://github.com/soerenbnoergaard/evoctl
  - https://github.com/TheOnlyJoey/MixiD
  - https://github.com/charlesmulder/alsa-audient-id14
  - https://github.com/r00tman/mymixer

- Check how does PipeWire and ALSA go together with the current setup:
- https://github.com/basecamp/omarchy/discussions/137
- https://ro-che.info/articles/2020-07-10-audient-evo4-pulseaudio

## License

Public domain. Free for all. Give credit as you see fit :-). See [LICENSE](LICENSE).
