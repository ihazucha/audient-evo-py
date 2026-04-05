"""EVO configuration save/load (JSON).

Per-device config paths:
  ~/.config/audient-evo-py/evo4/config.json
  ~/.config/audient-evo-py/evo8/config.json
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "audient-evo-py"


def _device_dir(device_name: str) -> Path:
    return CONFIG_DIR / device_name


def config_file(device_name: str) -> Path:
    return _device_dir(device_name) / "config.json"


def mixer_state_file(device_name: str) -> Path:
    return _device_dir(device_name) / ".mixer-state.json"



def load_mixer_state(device_name: str, path=None) -> dict | None:
    """Load the MU60 shadow state. Returns None if no shadow exists yet."""
    p = Path(path) if path else mixer_state_file(device_name)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_mixer_state(device_name: str, state: dict, path=None):
    """Persist MU60 shadow state to disk."""
    p = Path(path) if path else mixer_state_file(device_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def snapshot(evo) -> dict:
    """Read all current device settings into a dict."""
    data = evo.decode_status(evo.get_status_raw())
    mixer = load_mixer_state(evo.spec.name)
    if mixer is not None:
        data["mixer"] = mixer
    return data


def save(evo, path=None) -> Path:
    """Save current device state to JSON file."""
    path = Path(path) if path else config_file(evo.spec.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(evo), indent=2) + "\n")
    return path


def load(device_name: str, path=None) -> dict:
    """Load config dict from JSON file."""
    path = Path(path) if path else config_file(device_name)
    return json.loads(path.read_text())


def apply(evo, data: dict):
    """Apply a config dict to the device."""
    spec = evo.spec
    if "monitor" in data and evo.spec.has_monitor:
        evo.set_monitor(data["monitor"])

    # Output volume/mute
    if spec.num_output_pairs == 1:
        if "output" in data:
            out = data["output"]
            if "volume" in out:
                evo.set_volume(out["volume"])
            if "mute" in out:
                evo.set_mute("output", out["mute"])
    else:
        for pair in range(spec.num_output_pairs):
            key = f"output{pair+1}"
            if key in data:
                out = data[key]
                if "volume" in out:
                    evo.set_volume(out["volume"], output_pair=pair)
                if "mute" in out:
                    evo.set_mute(key, out["mute"])

    # Input gain/mute/phantom
    for i in range(spec.num_inputs):
        ch = f"input{i+1}"
        if ch in data:
            inp = data[ch]
            if "gain" in inp:
                evo.set_gain(ch, inp["gain"])
            if "mute" in inp:
                evo.set_mute(ch, inp["mute"])
            if "phantom" in inp:
                evo.set_phantom(ch, inp["phantom"])

    # Mixer
    if "mixer" in data:
        mx = data["mixer"]
        for i in range(spec.num_inputs):
            key = f"input{i+1}"
            if key in mx:
                evo.set_mixer_input(i + 1, mx[key]["volume"], mx[key].get("pan", 0.0))
        if "output" in mx:
            o = mx["output"]
            evo.set_mixer_output(o["volume"], o.get("pan_l", -100.0), o.get("pan_r", 100.0))
        if "loopback" in mx:
            lb = mx["loopback"]
            evo.set_mixer_loopback(lb["volume"], lb.get("pan_l", -100.0), lb.get("pan_r", 100.0))
        save_mixer_state(evo.spec.name, mx)


def load_and_apply(evo, path=None) -> dict:
    """Load config from file and apply to device."""
    data = load(evo.spec.name, path)
    apply(evo, data)
    return data
