"""Diagnostic info collector for remote tester support.

Collects system, USB, kernel module, audio stack, and device info
without requiring a connected device. Output is JSON-serializable.
"""

import glob
import os
import platform
import subprocess
import sys

from evo.devices import DEVICES, detect_devices


def _run(cmd: str, timeout: int = 5) -> str:
    """Run a shell command and return stdout, or error string on failure."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        return "<timeout>"
    except Exception as e:
        return f"<error: {e}>"


def _file_exists_info(path: str) -> dict:
    """Check if a file exists and return path + permissions info."""
    expanded = os.path.expanduser(path)
    if os.path.exists(expanded):
        try:
            stat = os.stat(expanded)
            return {"path": expanded, "exists": True, "mode": oct(stat.st_mode)}
        except OSError as e:
            return {"path": expanded, "exists": True, "stat_error": str(e)}
    return {"path": expanded, "exists": False}


def _glob_files(pattern: str) -> list[str]:
    """Return matching files for a glob pattern (with ~ expansion)."""
    return sorted(glob.glob(os.path.expanduser(pattern)))


def collect_diagnostics() -> dict:
    """Collect all diagnostic info. Returns a JSON-serializable dict."""
    diag = {}

    # System
    diag["system"] = {
        "kernel": platform.release(),
        "python": sys.version,
        "distro": _run("cat /etc/os-release 2>/dev/null | head -2"),
        "arch": platform.machine(),
    }

    # USB devices
    diag["usb"] = {
        "lsusb_audient": _run("lsusb -d 2708:"),
        "dev_nodes": {
            spec.dev_path: _file_exists_info(spec.dev_path)
            for spec in DEVICES.values()
        },
    }

    # Kernel module
    diag["kmod"] = {
        "lsmod": _run("lsmod | grep evo_raw"),
        "lsmod_legacy": _run("lsmod | grep evo4_raw"),
        "dkms": _run("dkms status 2>/dev/null | grep evo"),
    }

    # Udev rules
    diag["udev"] = {
        "rules": _glob_files("/etc/udev/rules.d/99-evo*.rules"),
    }

    # Audio stack
    diag["audio"] = {
        "pipewire": _run("systemctl --user is-active pipewire.service"),
        "wireplumber": _run("systemctl --user is-active wireplumber.service"),
        "wpctl_status": _run("wpctl status 2>/dev/null | grep -i evo"),
    }

    # Installed configs
    home = os.path.expanduser("~")
    diag["configs"] = {
        "pipewire": _glob_files("~/.config/pipewire/pipewire.conf.d/evo*"),
        "wireplumber": _glob_files("~/.config/wireplumber/wireplumber.conf.d/*evo*")
                     + _glob_files("~/.config/wireplumber/wireplumber.conf.d/alsa-soft-mixer.conf"),
        "systemd_setup": _glob_files("~/.config/systemd/user/evo*-setup.service"),
        "systemd_load": _glob_files("~/.config/systemd/user/evo*-load-config.service"),
        "local_bin": _glob_files("~/.local/bin/evo*"),
    }

    # Device status (for each connected device)
    diag["devices"] = {}
    for spec in detect_devices():
        try:
            from evo.controller import EVOController
            evo = EVOController(spec)
            status = evo.decode_status(evo.get_status_raw())
            diag["devices"][spec.name] = {"status": status}
        except Exception as e:
            diag["devices"][spec.name] = {"error": str(e)}

    # Saved configs
    diag["saved_configs"] = {}
    for name in DEVICES:
        path = os.path.expanduser(f"~/.config/audient-evo-py/{name}/config.json")
        diag["saved_configs"][name] = _file_exists_info(path)

    return diag
