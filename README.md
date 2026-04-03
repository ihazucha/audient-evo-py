# audient-evo-py

Audient EVO4 control app only releases for Windows/macOS and existing attempts to reverse-engineer it were incomplete and abandoned (now LLMs make the boring part of it fun).

`evoctl and evotui` allows live configuring of the device without the need to swap drivers or otherwise interrupt audio streaming.

**How it works?** A small kernel module binds to the EVO 4's unused DFU interface to send USB control transfers, coexisting with `snd-usb-audio`. Audio streaming is never interrupted.

## Screenshots

| Controls | Loopback Mixer |
|----------|----------------|
| ![TUI controls](screenshots/tui_controls.jpg) | ![TUI mixer](screenshots/tui_mixer.jpg) |

```
audient-evo-py master ❯ evoctl set volume -20
[SET] Volume: -20.00 dB  (raw=0xEC00)

audient-evo-py master ❯ evoctl set gain 50 -t input1
[SET] Gain input1: +50.00 dB  (raw=0x3200)

audient-evo-py master ❯ evoctl set monitor 50
[SET] Monitor: 50% (0=input, 100=playback)

audient-evo-py master ❯ evoctl status -f json
{
  "monitor": 50,
  "output": {
    "volume": -20.0,
    "mute": false
  },
  "input1": {
    "gain": 50.0,
    "mute": false,
    "phantom": false
  },
  "input2": {
    "gain": -8.0,
    "mute": false,
    "phantom": false
  }
}
```

## Requirements

- Linux with `snd-usb-audio` (standard kernel audio)
- Kernel headers (`linux-headers` package) and DKMS - for the kernel module
- Python 3.10+ - the only runtime dependency; `pipx` is recommended for install

`pytest` is used for tests (no extra dependencies otherwise).

## Install

### Kernel module

Installs via DKMS, adds a udev rule, and loads the module. Users in the `dialout`
group can access `/dev/evo4`.

```bash
cd kmod
sudo ./install.sh
```

To uninstall:

```bash
cd kmod
sudo ./uninstall.sh
```

### evoctl / evotui

No external Python dependencies. Run directly from the repo:

```bash
python evoctl.py set volume 75
python -m tui.app
```

Or install with `pipx` for system-wide `evoctl` and `evotui` commands:

```bash
pipx install .
```

### WirePlumber config (optional, recommended)

The EVO 4 exposes 4 USB audio channels - 2 physical I/O and a loopback bus on CH3/CH4.
Without configuration, PipeWire treats this as a "Surround 4.0" device and upmixes stereo
audio incorrectly. The provided config:

- Disables upmix so stereo apps only write to CH1/CH2 (main output)
- Creates virtual sinks/sources: `evo4_loopback_output`, `evo4_mic`, `evo4_loopback_capture`
- Disables idle suspension (prevents clicks on stream start)
- Sets EVO 4 nodes as default sink/source at login

```bash
bash wireplumber/evo4-setup-install.sh
```

See [wireplumber/README.md](wireplumber/README.md) for signal flow diagrams and details.

## Usage

### CLI

```bash
# Output volume (dB or 0-100)
evoctl set volume -20
evoctl get volume

# Input gain per-channel
evoctl set gain 50 -t input1
evoctl get gain

# Monitor mix (0=input only, 100=playback only)
evoctl set monitor 50
evoctl get monitor

# Mute
evoctl set mute on -t output
evoctl get mute -t input1

# Phantom power (48V)
evoctl set phantom on -t input1
evoctl get phantom -t input1

# Loopback mixer - route inputs/playback to loopback capture
evoctl mixer input1 --volume -6 --pan 0
evoctl mixer output --volume -6 --pan-l -100 --pan-r 100
evoctl mixer loopback --volume -128

# Show all parameters
evoctl status
evoctl status -f json
```

Targets for mute: `input1`, `input2`, `output`. Targets for phantom: `input1`, `input2`.
Mixer volume range: [-128, 8] dB (-128 = mute). Pan: -100 (left) to 100 (right).
Aliases: `g` for `get`, `s` for `set`, `m` for `mixer`.

### TUI

```bash
evotui
```

### Saved state

Mixer settings are saved to `~/.config/audient-evo-py/.mixer-state.json` and updated on
every mixer change. The EVO 4 does not expose a readable register for mixer state over USB,
so this file is the authoritative source for loopback mixer values between sessions.

## Components

| Component | Description |
|-----------|-------------|
| `kmod/` | Out-of-tree kernel module (`evo4_raw.c`), exposes `/dev/evo4` |
| `evoctl` | CLI - get/set all device parameters |
| `evotui` | Terminal UI |
| `wireplumber/` | PipeWire + WirePlumber config for correct channel mapping |

See [DESIGN.md](DESIGN.md) for architecture, protocol, and USB entity details.

## Related Projects

Existing (partial) implementation that did not solve the problem as I imagined (no need for driver swap in particular) but were helpful in creating this.

- [subsubl/Evo4mixer](https://github.com/subsubl/Evo4mixer)
- [vijay-prema/audient-evo-linux-tools](https://github.com/vijay-prema/audient-evo-linux-tools/tree/main)
- [soerenbnoergaard/evoctl](https://github.com/soerenbnoergaard/evoctl)
- [TheOnlyJoey/MixiD](https://github.com/TheOnlyJoey/MixiD)
- [charlesmulder/alsa-audient-id14](https://github.com/charlesmulder/alsa-audient-id14)
- [r00tman/mymixer](https://github.com/r00tman/mymixer)

## Other Audient / EVO Devices

I'm looking to extend support to other Audient EVO and ID-series devices. If you own one
and are willing to cooperate or lend hardware, please open an issue.

## License

Public domain. Free for all. Give credit as you see fit :-). See [LICENSE](LICENSE).
