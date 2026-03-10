"""Audient EVO4 controller using direct USB control transfers (Windows).

On Windows, snd-usb-audio doesn't exist. The Audient vendor driver handles
audio, and we use WinUSB via pyusb to send control transfers to the device.
This requires driver_swap.ps1 to switch to WinUSB first.
"""

import os
import sys
import math
from contextlib import contextmanager

from usb.backend.libusb1 import get_backend
import usb.core
import usb.util

AUDIENT_VENDOR_ID = 0x2708
EVO4_ID = 0x0006
USB_INTERFACE = 0x00

# USB Audio Class 2.0 request constants
REQTYPE_SET = 0x21  # Host->Device, Class, Interface
REQTYPE_GET = 0xa1  # Device->Host, Class, Interface
REQ_CUR = 0x01      # SET CUR / GET CUR

# Known control request parameters (from USB captures)
# wIndex = (EntityID << 8) | InterfaceNumber
# wValue = (ControlSelector << 8) | ChannelNumber
CTRL_VOLUME = {'wValue': 0x0000, 'wIndex': 0x3B00}  # Extension Unit 59


def _volume_percent_to_dB(volume: int) -> float:
    """Map volume 0-100 to dB -96.0-0.0 with a power curve anchored at 50 -> -20 dB."""
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return -96.0 * (1.0 - (volume / 100.0) ** n)


def _dB_to_volume_percent(db: float) -> int:
    """Inverse of _volume_percent_to_dB: map dB -96.0-0.0 to volume 0-100."""
    db = max(-96.0, min(0.0, db))
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return round(100.0 * (1.0 + db / 96.0) ** (1.0 / n))


@contextmanager
def _claim_usb_interface(device: usb.core.Device, interface: int):
    usb.util.claim_interface(device, interface)
    try:
        yield
    finally:
        usb.util.release_interface(device, interface)


class EVO4Controller:
    def __init__(self):
        lib_path = os.environ.get('LIBUSB_PATH')
        backend = get_backend(find_library=lambda x: lib_path) if lib_path else get_backend()
        assert backend is not None, "libusb v1.0 not found"

        self.dev = usb.core.find(
            idVendor=AUDIENT_VENDOR_ID, idProduct=EVO4_ID, backend=backend
        )
        if self.dev is None:
            raise RuntimeError(
                f"Audient EVO4 not found (VID:{AUDIENT_VENDOR_ID:#06x} PID:{EVO4_ID:#06x}). "
                "Ensure WinUSB driver is active (run driver_swap.ps1)."
            )

    def _ctrl_set(self, wValue, wIndex, data):
        with _claim_usb_interface(self.dev, USB_INTERFACE):
            res = self.dev.ctrl_transfer(REQTYPE_SET, REQ_CUR, wValue, wIndex, data)
            if res != len(data):
                raise IOError(f"SET_CUR failed: wrote {res}/{len(data)} bytes")

    def _ctrl_get(self, wValue, wIndex, length):
        with _claim_usb_interface(self.dev, USB_INTERFACE):
            return self.dev.ctrl_transfer(REQTYPE_GET, REQ_CUR, wValue, wIndex, length)

    # --- Output Volume ---

    def get_volume(self) -> list[int]:
        data = self._ctrl_get(**CTRL_VOLUME, length=4)
        db = int.from_bytes(data, 'little', signed=True) / 256.0
        pct = _dB_to_volume_percent(db)
        return [pct, pct]  # mono control, return as stereo

    def set_volume(self, percent: int, channel: int | None = None):
        db = _volume_percent_to_dB(percent)
        data = int(db * 256.0).to_bytes(4, 'little', signed=True)
        self._ctrl_set(**CTRL_VOLUME, data=data)

    # --- Stubs for features not yet captured on Windows ---

    def get_gain(self) -> list[int]:
        raise NotImplementedError("Input gain control not yet implemented for Windows")

    def set_gain(self, percent: int, channel: int | None = None):
        raise NotImplementedError("Input gain control not yet implemented for Windows")

    def get_mute(self) -> bool:
        raise NotImplementedError("Mute control not yet implemented for Windows")

    def set_mute(self, muted: bool):
        raise NotImplementedError("Mute control not yet implemented for Windows")

    def get_mix(self) -> int:
        raise NotImplementedError("Monitor mix control not yet implemented for Windows")

    def set_mix(self, ratio: int):
        raise NotImplementedError("Monitor mix control not yet implemented for Windows")
