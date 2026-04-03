# audient-evo-py

Original Audient EVO (4) app is Windows/macOS only and existing attempts to reverse-engineer it were incomplete and abandoned (now LLMs make the boring part of it fun).

`evoctl` and `evotui` allow live config of the device without a need to swap drivers or otherwise interrupt audio streaming.

**How?** A small kernel module binds to the EVO 4's unused DFU interface to send USB control messages, coexisting with `snd-usb-audio`. Audio streaming is never interrupted.

| Controls | Loopback Mixer |
|----------|----------------|
| ![TUI controls](screenshots/tui_controls.jpg) | ![TUI mixer](screenshots/tui_mixer.jpg) |

## Requirements

- Linux with `snd-usb-audio` (standard kernel audio)
- Kernel headers (`linux-headers` package) and DKMS - for the kernel module
- Python 3.10+ - the only runtime dependency; `pipx` is recommended for install

`pytest` is used for tests.

## Install

### Kernel module

Installs via DKMS, adds a udev rule, and loads the module. Users in the `dialout`
group can access `/dev/evo4`.

```bash
cd kmod
sudo ./install.sh
```

### evoctl / evotui

No external Python dependencies. Runs directly from the repo:

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

```bash
# --- CLI ---
evoctl set volume -20        # dB or 0-100
evoctl get volume
evoctl set gain 50 -t input1 # input gain per-channel
evoctl get gain
evoctl set monitor 50        # 0=input only, 100=playback only
evoctl get monitor
evoctl set mute on -t output
evoctl get mute -t input1
evoctl set phantom on -t input1
evoctl get phantom -t input1

# loopback mixer - route inputs/playback to loopback capture
evoctl mixer input1 --volume -6 --pan 0
evoctl mixer output --volume -6 --pan-l -100 --pan-r 100
evoctl mixer loopback --volume -128

evoctl status
evoctl status -f json
evoctl save .config/audient-evo-py/config.json
evoctl load

# --- TUI ---
python -m tui
# or simply (after pipx install)
evotui
```

Mixer settings are write-only; changes are auto-saved to `~/.config/audient-evo-py/.mixer-state.json`. Device controls can be saved/loaded via CLI or TUI.

## Components

| Component | Description |
|-----------|-------------|
| `kmod/` | Out-of-tree kernel module (`evo4_raw.c`), exposes `/dev/evo4` |
| `evo4/` | backend - kmod wrapper and controller |
| `tui/` | Terminal UI using curses |
| `wireplumber/` | PipeWire + WirePlumber config for correct channel mapping |

See [DESIGN.md](DESIGN.md) for architecture, protocol, and USB entity details.

## Related Projects

Existing implementations - partially working with quirks and caveats (need to swap driver to change setting in particular) but helpful nonetheless.

- [subsubl/Evo4mixer](https://github.com/subsubl/Evo4mixer)
- [vijay-prema/audient-evo-linux-tools](https://github.com/vijay-prema/audient-evo-linux-tools/tree/main)
- [soerenbnoergaard/evoctl](https://github.com/soerenbnoergaard/evoctl)
- [TheOnlyJoey/MixiD](https://github.com/TheOnlyJoey/MixiD)
- [charlesmulder/alsa-audient-id14](https://github.com/charlesmulder/alsa-audient-id14)
- [r00tman/mymixer](https://github.com/r00tman/mymixer)

## Notice

If demand arises I like to support other Audient EVO (possibly other devices). If you own one and are willing to cooperate, please open an issue.

## License

Public domain. Free for all. Give credit as you see fit :-). See [LICENSE](LICENSE).
