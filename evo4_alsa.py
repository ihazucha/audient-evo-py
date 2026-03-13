"""Audient EVO4 controller using ALSA mixer controls (Linux).

Uses the snd-usb-audio kernel driver's mixer interface, which sends USB
control transfers on our behalf without disrupting audio streaming.

ALSA controls exposed by snd-usb-audio for EVO4:
  Unit 10: "EVO4  Playback Volume" - output volume, 4ch, -12700..0 cB
  Unit 11: "Mic Playback Volume"   - input gain, 4ch, -800..5000 cB
  Unit 59: "Extension Unit Switch"  - mute/monitor toggle, boolean

Monitor mix (Mixer Unit 60) is NOT exposed by snd-usb-audio. When the
evo4_raw kernel module is loaded (/dev/evo4), we use it for true hardware
monitor mix control. Otherwise, falls back to a volume/gain approximation.
"""

import alsaaudio
import os
import logging

log = logging.getLogger(__name__)


# ALSA control names (from alsaaudio.mixers())
CTRL_OUTPUT_VOLUME = "EVO4 "          # Feature Unit 10, 4ch, range 0-254
CTRL_INPUT_GAIN = "Mic"               # Feature Unit 11, 4ch, range 0-116



def _find_card_index() -> int:
    """Find the ALSA card index for the EVO4."""
    for i in range(32):
        try:
            with open(f"/proc/asound/card{i}/id") as f:
                if f.read().strip() == "EVO4":
                    return i
        except FileNotFoundError:
            continue
    raise RuntimeError("Audient EVO4 not found in ALSA cards")


class EVO4Controller:
    def __init__(self, card_index: int | None = None):
        self.card_index = card_index if card_index is not None else _find_card_index()
        # Verify we can open the controls
        self._mixer(CTRL_OUTPUT_VOLUME)

    def _mixer(self, control: str) -> alsaaudio.Mixer:
        return alsaaudio.Mixer(control=control, cardindex=self.card_index)

    # --- Output Volume (Feature Unit 10) ---
    # ALSA raw range: 0..254, linear in dB (-127.00..0.00 dB).
    # Perceptual curve: raw = 254 * (1 - (1 - p/100)^2)
    # Maps 50% → ~-32 dB instead of linear's -63.5 dB.

    _VOL_MAX_RAW = 254

    @staticmethod
    def _pct_to_raw(percent: int) -> int:
        """Convert perceptual 0-100% to raw 0-254 using cubic curve."""
        p = max(0, min(100, percent)) / 100.0
        return round(254 * (1.0 - (1.0 - p) ** 2))

    @staticmethod
    def _raw_to_pct(raw: int) -> int:
        """Convert raw 0-254 to perceptual 0-100% (inverse cubic)."""
        r = max(0, min(254, raw)) / 254.0
        return round(100.0 * (1.0 - (1.0 - r) ** 0.5))

    def get_volume(self) -> list[int]:
        """Get output volume as list of per-channel percentages (0-100)."""
        m = self._mixer(CTRL_OUTPUT_VOLUME)
        return [self._raw_to_pct(round(v * 254 / 100)) for v in m.getvolume()]

    def set_volume(self, percent: int, channel: int | None = None):
        """Set output volume (0-100). channel is 1-based, None = all 4."""
        m = self._mixer(CTRL_OUTPUT_VOLUME)
        # Convert perceptual % to raw, then to alsaaudio's linear %
        alsa_pct = round(self._pct_to_raw(percent) * 100 / 254)
        if channel is not None:
            m.setvolume(alsa_pct, channel - 1)
        else:
            for ch in range(4):
                m.setvolume(alsa_pct, ch)

    # --- Input Gain (Feature Unit 11) ---
    # ALSA range: -800..5000 cB, i.e. -8.00..+50.00 dB

    def get_gain(self) -> list[int]:
        """Get input gain as list of per-channel percentages (0-100)."""
        m = self._mixer(CTRL_INPUT_GAIN)
        return m.getvolume()

    def set_gain(self, percent: int, channel: int | None = None):
        """Set input gain (0-100). channel is 1-based, None = all 4."""
        m = self._mixer(CTRL_INPUT_GAIN)
        if channel is not None:
            m.setvolume(percent, channel - 1)
        else:
            for ch in range(4):
                m.setvolume(percent, ch)

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
        self._require_kmod()
        import evo4_kmod
        with evo4_kmod.open_device() as fd:
            data = evo4_kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=4)
            return int.from_bytes(data[:4], "little") == 1

    def set_mute(self, target: str, muted: bool):
        """Set mute state for target (input1, input2, output)."""
        wValue, wIndex = self._MUTE_TARGETS[target]
        self._require_kmod()
        import evo4_kmod
        with evo4_kmod.open_device() as fd:
            data = (1 if muted else 0).to_bytes(4, "little")
            evo4_kmod.set_cur(fd, wValue=wValue, wIndex=wIndex, data=data)

    # --- Monitor Mix (Extension Unit 56) ---
    # Hardware monitor mix is controlled via EU56 CS=0 CN=0.
    # Linear range: 0 = full input, 127 = full playback.
    # Requires the evo4_raw kernel module (/dev/evo4).
    # Falls back to volume/gain approximation if unavailable.

    _EU56_WINDEX = 0x3800   # (EntityID=0x38 << 8) | Interface=0
    _EU56_WVALUE = 0x0000   # (CS=0 << 8) | CN=0

    def _has_kmod(self) -> bool:
        return os.path.exists("/dev/evo4")

    def _kmod_get_mix(self) -> int:
        import evo4_kmod
        with evo4_kmod.open_device() as fd:
            data = evo4_kmod.get_cur(fd, wValue=self._EU56_WVALUE,
                                     wIndex=self._EU56_WINDEX, length=2)
            raw = int.from_bytes(data[:2], "little")
            # 0=full input, 127=full playback → map to 0-100
            return round(raw * 100 / 127)

    def _kmod_set_mix(self, ratio: int):
        import evo4_kmod
        with evo4_kmod.open_device() as fd:
            # 0-100 → 0-127
            raw = round(ratio * 127 / 100)
            raw = max(0, min(127, raw))
            data = raw.to_bytes(2, "little")
            evo4_kmod.set_cur(fd, wValue=self._EU56_WVALUE,
                              wIndex=self._EU56_WINDEX, data=data)

    def _require_kmod(self):
        if not self._has_kmod():
            raise RuntimeError("Monitor mix requires the evo4_raw kernel module (/dev/evo4)")

    def get_mix(self) -> int:
        """Get monitor mix ratio (0=input only, 100=playback only)."""
        self._require_kmod()
        return self._kmod_get_mix()

    def set_mix(self, ratio: int):
        """Set monitor mix ratio (0=input only, 100=playback only)."""
        self._require_kmod()
        self._kmod_set_mix(ratio)
