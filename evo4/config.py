"""EVO4 configuration save/load (JSON).

Format:
  {
    "monitor": <int 0-100>,
    "output":  { "volume": <float dB [-96, 0]>, "mute": <bool> },
    "input1":  { "gain": <float dB [-8, 50]>, "mute": <bool>, "phantom": <bool> },
    "input2":  { "gain": <float dB [-8, 50]>, "mute": <bool>, "phantom": <bool> }
  }
"""

import json
from pathlib import Path

CONFIG_DIR        = Path.home() / ".config" / "audient-evo-py"
CONFIG_FILE       = CONFIG_DIR / "config.json"
MIXER_STATE_FILE  = CONFIG_DIR / ".mixer-state.json"


def load_mixer_state(path=None) -> dict | None:
    """Load the MU60 shadow state. Returns None if no shadow exists yet."""
    p = Path(path) if path else MIXER_STATE_FILE
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_mixer_state(state: dict, path=None):
    """Persist MU60 shadow state to disk."""
    p = Path(path) if path else MIXER_STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def snapshot(evo) -> dict:
    """Read all current device settings into a dict."""
    data = {
        "monitor": evo.get_mix(),
        "output": {
            "volume": evo.get_volume(),
            "mute":   evo.get_mute("output"),
        },
        "input1": {
            "gain":    evo.get_gain("input1"),
            "mute":    evo.get_mute("input1"),
            "phantom": evo.get_phantom("input1"),
        },
        "input2": {
            "gain":    evo.get_gain("input2"),
            "mute":    evo.get_mute("input2"),
            "phantom": evo.get_phantom("input2"),
        },
    }
    mixer = load_mixer_state()
    if mixer is not None:
        data["mixer"] = mixer
    return data


def save(evo, path=None) -> Path:
    """Save current device state to JSON file."""
    path = Path(path) if path else CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(evo), indent=2) + "\n")
    return path


def load(path=None) -> dict:
    """Load config dict from JSON file."""
    path = Path(path) if path else CONFIG_FILE
    return json.loads(path.read_text())


def apply(evo, data: dict):
    """Apply a config dict to the device."""
    if "monitor" in data:
        evo.set_mix(data["monitor"])
    if "output" in data:
        out = data["output"]
        if "volume" in out:
            evo.set_volume(out["volume"])
        if "mute" in out:
            evo.set_mute("output", out["mute"])
    for ch in ("input1", "input2"):
        if ch in data:
            inp = data[ch]
            if "gain" in inp:
                evo.set_gain(ch, inp["gain"])
            if "mute" in inp:
                evo.set_mute(ch, inp["mute"])
            if "phantom" in inp:
                evo.set_phantom(ch, inp["phantom"])
    if "mixer" in data:
        mx = data["mixer"]
        for key in ("input1", "input2"):
            if key in mx:
                num = int(key[-1])
                evo.set_mixer_input(num, mx[key]["volume"], mx[key].get("pan", 0.0))
        if "output" in mx:
            o = mx["output"]
            evo.set_mixer_output(o["volume"], o.get("pan_l", -100.0), o.get("pan_r", 100.0))
        if "loopback" in mx:
            lb = mx["loopback"]
            evo.set_mixer_loopback(lb["volume"], lb.get("pan_l", -100.0), lb.get("pan_r", 100.0))
        save_mixer_state(mx)


def load_and_apply(evo, path=None) -> dict:
    """Load config from file and apply to device."""
    data = load(path)
    apply(evo, data)
    return data
