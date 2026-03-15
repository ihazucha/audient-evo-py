"""Audient EVO4 controller — all controls via evo4_raw kernel module.

Controls go through /dev/evo4 (USB control transfers) without
disrupting snd-usb-audio streaming.

Controls:
  Feature Unit 10: output volume, -127.00..0.00 dB
  Feature Unit 11: input gain, -8.00..+50.00 dB
  Extension Unit 56: monitor mix, 0..127
  Extension Unit 58: input mute, phantom power (48V)
  Extension Unit 59: output mute
"""

import math
from contextlib import contextmanager
from os.path import exists

from evo4 import kmod


# UAC2 Feature Unit control selectors
_CS_VOLUME = 2

# Feature Unit wIndex values: (EntityID << 8) | Interface
_FU10 = 0x0A00  # Output volume
_FU11 = 0x0B00  # Input gain

# Volume (FU10): effective range -96..0 dB, power curve anchored at 50% → -20 dB
_VOL_DB_MIN = -96.0
_VOL_DB_MAX = 0.0
_VOL_CURVE_N = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)

# Gain (FU11): -8.00..+50.00 dB
_GAIN_DB_MIN = -8.0
_GAIN_DB_MAX = 50.0

_NUM_CHANNELS = 2      # CH1 and CH2 (UAC descriptor reports 4 but CH3-4 are internal)


def _db_to_usb(db: float) -> int:
    """Convert dB to UAC2 16-bit signed (1/256 dB steps)."""
    return round(db * 256) & 0xFFFF


def _usb_to_db(raw: int) -> float:
    """Convert UAC2 16-bit signed to dB."""
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw / 256.0


class EVO4Controller:
    def __init__(self):
        self._require_kmod()
        self._fd = None

    def __enter__(self):
        self._fd = kmod.open_device()
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            self._fd.close()
            self._fd = None
        return False

    @contextmanager
    def _device(self):
        """Yield the shared fd (context manager mode) or a temporary one."""
        if self._fd is not None:
            yield self._fd
        else:
            with kmod.open_device() as fd:
                yield fd

    # --- Output Volume (Feature Unit 10) ---
    # Power curve: 50% → -20 dB, matching the EVO4 app's knob response

    @staticmethod
    def _vol_pct_to_db(percent: int) -> float:
        p = max(0, min(100, percent)) / 100.0
        return _VOL_DB_MIN * (1.0 - p ** _VOL_CURVE_N)

    @staticmethod
    def _vol_db_to_pct(db: float) -> int:
        db = max(_VOL_DB_MIN, min(_VOL_DB_MAX, db))
        return round(100.0 * (1.0 - db / _VOL_DB_MIN) ** (1.0 / _VOL_CURVE_N))

    def _get_fu_raw(self, unit: int, cn: int) -> int:
        """Read raw 16-bit USB value from a Feature Unit channel."""
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=(_CS_VOLUME << 8) | cn,
                                     wIndex=unit, length=2)
            return int.from_bytes(data[:2], "little", signed=True)

    def _set_fu_raw(self, unit: int, cn: int, raw: int):
        """Write raw 16-bit USB value to a Feature Unit channel."""
        with self._device() as fd:
            kmod.set_cur(fd, wValue=(_CS_VOLUME << 8) | cn,
                              wIndex=unit, data=(raw & 0xFFFF).to_bytes(2, "little"))

    def get_volume(self) -> list[int]:
        """Get output volume as list of per-channel percentages (0-100)."""
        return [self._vol_db_to_pct(_usb_to_db(self._get_fu_raw(_FU10, cn)))
                for cn in range(1, _NUM_CHANNELS + 1)]

    def get_volume_debug(self) -> list[tuple[int, int, float]]:
        """Get volume with debug info: list of (percent, raw, dB) per channel."""
        result = []
        for cn in range(1, _NUM_CHANNELS + 1):
            raw = self._get_fu_raw(_FU10, cn)
            db = _usb_to_db(raw)
            pct = self._vol_db_to_pct(db)
            result.append((pct, raw, db))
        return result

    def set_volume(self, percent: int, channel: int | None = None) -> tuple[int, float]:
        """Set output volume (0-100). channel is 1-based, None = all active.
        Returns (raw, dB) that was sent."""
        db = self._vol_pct_to_db(percent)
        raw = _db_to_usb(db)
        if channel is not None:
            self._set_fu_raw(_FU10, channel, raw)
        else:
            for cn in range(1, _NUM_CHANNELS + 1):
                self._set_fu_raw(_FU10, cn, raw)
        return (raw if raw <= 0x7FFF else raw - 0x10000, db)

    def set_volume_db(self, db: float, channel: int | None = None) -> tuple[int, float]:
        """Set output volume in dB (-96..0). Returns (raw, dB) that was sent."""
        db = max(_VOL_DB_MIN, min(_VOL_DB_MAX, db))
        raw = _db_to_usb(db)
        if channel is not None:
            self._set_fu_raw(_FU10, channel, raw)
        else:
            for cn in range(1, _NUM_CHANNELS + 1):
                self._set_fu_raw(_FU10, cn, raw)
        return (raw if raw <= 0x7FFF else raw - 0x10000, db)

    # --- Input Gain (Feature Unit 11) ---
    # Linear: 0% = -8 dB, 100% = +50 dB

    @staticmethod
    def _gain_pct_to_db(percent: int) -> float:
        p = max(0, min(100, percent)) / 100.0
        return _GAIN_DB_MIN + (_GAIN_DB_MAX - _GAIN_DB_MIN) * p

    @staticmethod
    def _gain_db_to_pct(db: float) -> int:
        db = max(_GAIN_DB_MIN, min(_GAIN_DB_MAX, db))
        return round(100.0 * (db - _GAIN_DB_MIN) / (_GAIN_DB_MAX - _GAIN_DB_MIN))

    def get_gain(self) -> list[int]:
        """Get input gain as list of per-channel percentages (0-100)."""
        return [self._gain_db_to_pct(_usb_to_db(self._get_fu_raw(_FU11, cn)))
                for cn in range(1, _NUM_CHANNELS + 1)]

    def get_gain_debug(self) -> list[tuple[int, int, float]]:
        """Get gain with debug info: list of (percent, raw, dB) per channel."""
        result = []
        for cn in range(1, _NUM_CHANNELS + 1):
            raw = self._get_fu_raw(_FU11, cn)
            db = _usb_to_db(raw)
            pct = self._gain_db_to_pct(db)
            result.append((pct, raw, db))
        return result

    def set_gain(self, percent: int, channel: int | None = None) -> tuple[int, float]:
        """Set input gain (0-100). channel is 1-based, None = all active.
        Returns (raw, dB) that was sent."""
        db = self._gain_pct_to_db(percent)
        raw = _db_to_usb(db)
        if channel is not None:
            self._set_fu_raw(_FU11, channel, raw)
        else:
            for cn in range(1, _NUM_CHANNELS + 1):
                self._set_fu_raw(_FU11, cn, raw)
        return (raw if raw <= 0x7FFF else raw - 0x10000, db)

    def set_gain_db(self, db: float, channel: int | None = None) -> tuple[int, float]:
        """Set input gain in dB (-8..+50). Returns (raw, dB) that was sent."""
        db = max(_GAIN_DB_MIN, min(_GAIN_DB_MAX, db))
        raw = _db_to_usb(db)
        if channel is not None:
            self._set_fu_raw(_FU11, channel, raw)
        else:
            for cn in range(1, _NUM_CHANNELS + 1):
                self._set_fu_raw(_FU11, cn, raw)
        return (raw if raw <= 0x7FFF else raw - 0x10000, db)

    # --- Mute (via kmod: Entity 58 for inputs, Entity 59 for output) ---
    # Data: 4 bytes LE, 0x01=muted, 0x00=unmuted

    _MUTE_TARGETS = {
        "input1": (0x0200, 0x3A00),  # Entity 58, CS=2, CN=0
        "input2": (0x0201, 0x3A00),  # Entity 58, CS=2, CN=1
        "output": (0x0100, 0x3B00),  # Entity 59, CS=1, CN=0
    }

    def get_mute(self, target: str) -> bool:
        """Get mute state for target (input1, input2, output)."""
        wValue, wIndex = self._MUTE_TARGETS[target]
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=4)
            return int.from_bytes(data[:4], "little") == 1

    def set_mute(self, target: str, muted: bool):
        """Set mute state for target (input1, input2, output)."""
        wValue, wIndex = self._MUTE_TARGETS[target]
        with self._device() as fd:
            data = (1 if muted else 0).to_bytes(4, "little")
            kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)

    # --- Phantom Power (Extension Unit 58, CS=0) ---
    # 4 bytes LE: 0x01=on, 0x00=off. Per-channel (CN=0 for input1, CN=1 for input2).

    _PHANTOM_TARGETS = {
        "input1": (0x0000, 0x3A00),  # Entity 58, CS=0, CN=0
        "input2": (0x0001, 0x3A00),  # Entity 58, CS=0, CN=1
    }

    def get_phantom(self, target: str) -> bool:
        """Get 48V phantom power state for target (input1, input2)."""
        wValue, wIndex = self._PHANTOM_TARGETS[target]
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=4)
            return int.from_bytes(data[:4], "little") == 1

    def set_phantom(self, target: str, enabled: bool):
        """Set 48V phantom power for target (input1, input2)."""
        wValue, wIndex = self._PHANTOM_TARGETS[target]
        with self._device() as fd:
            data = (1 if enabled else 0).to_bytes(4, "little")
            kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)

    # --- Monitor Mix (Extension Unit 56) ---
    # Linear range: 0 = full input, 127 = full playback.

    _EU56_WINDEX = 0x3800   # (EntityID=0x38 << 8) | Interface=0
    _EU56_WVALUE = 0x0000   # (CS=0 << 8) | CN=0

    def _require_kmod(self):
        if not exists("/dev/evo4"):
            raise RuntimeError("evo4_raw kernel module not loaded (/dev/evo4 not found)")

    def get_mix(self) -> int:
        """Get monitor mix ratio (0=input only, 100=playback only)."""
        with self._device() as fd:
            data = kmod.get_cur(fd, wValue=self._EU56_WVALUE,
                                     wIndex=self._EU56_WINDEX, length=2)
            raw = int.from_bytes(data[:2], "little")
            return round(raw * 100 / 127)

    def set_mix(self, ratio: int):
        """Set monitor mix ratio (0=input only, 100=playback only)."""
        with self._device() as fd:
            raw = max(0, min(127, round(ratio * 127 / 100)))
            data = raw.to_bytes(2, "little")
            kmod.set_cur(fd, wValue=self._EU56_WVALUE,
                              wIndex=self._EU56_WINDEX, data=data)
