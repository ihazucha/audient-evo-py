"""Device specifications for Audient EVO series interfaces."""

from dataclasses import dataclass
from os.path import exists


@dataclass(frozen=True)
class DeviceSpec:
    name: str              # "evo4", "evo8"
    display_name: str      # "EVO 4", "EVO 8"
    usb_pid: int           # 0x0006, 0x0007
    dev_path: str          # "/dev/evo4", "/dev/evo8"
    num_inputs: int        # 2, 4
    num_output_pairs: int  # 1, 2
    gain_db_min: float     # -8.0, 0.0
    gain_db_max: float     # 50.0, 58.0
    vol_db_min: float      # -96.0
    vol_db_max: float      # 0.0
    mixer_inputs: int      # 6, 10
    mixer_outputs: int     # 2, 4
    num_mute_targets: int  # 3, 6
    has_monitor: bool      # EU56 direct monitor blend (EVO4 only)


EVO4 = DeviceSpec(
    name="evo4",
    display_name="EVO 4",
    usb_pid=0x0006,
    dev_path="/dev/evo4",
    num_inputs=2,
    num_output_pairs=1,
    gain_db_min=-8.0,
    gain_db_max=50.0,
    vol_db_min=-96.0,
    vol_db_max=0.0,
    mixer_inputs=6,
    mixer_outputs=2,
    num_mute_targets=3,
    has_monitor=True,
)

EVO8 = DeviceSpec(
    name="evo8",
    display_name="EVO 8",
    usb_pid=0x0007,
    dev_path="/dev/evo8",
    num_inputs=4,
    num_output_pairs=2,
    gain_db_min=0.0,
    gain_db_max=58.0,
    vol_db_min=-96.0,
    vol_db_max=0.0,
    mixer_inputs=10,
    mixer_outputs=4,
    num_mute_targets=6,
    has_monitor=False,
)

DEVICES = {"evo4": EVO4, "evo8": EVO8}


def detect_devices() -> list[DeviceSpec]:
    """Check which /dev/evo* paths exist, return matching specs."""
    return [spec for spec in DEVICES.values() if exists(spec.dev_path)]
