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
CTRL_EXT_SWITCH = "Extension Unit"    # Extension Unit 59, boolean (mute)


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
    # ALSA range: -12700..0 cB (centibels), i.e. -127.00..0.00 dB

    def get_volume(self) -> list[int]:
        """Get output volume as list of per-channel percentages (0-100)."""
        m = self._mixer(CTRL_OUTPUT_VOLUME)
        return m.getvolume()

    def set_volume(self, percent: int, channel: int | None = None):
        """Set output volume (0-100). channel is 1-based, None = all 4."""
        m = self._mixer(CTRL_OUTPUT_VOLUME)
        if channel is not None:
            m.setvolume(percent, channel - 1)
        else:
            for ch in range(4):
                m.setvolume(percent, ch)

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

    # --- Mute (Extension Unit 59) ---

    def get_mute(self) -> bool:
        """Get mute state."""
        m = self._mixer(CTRL_EXT_SWITCH)
        mute_vals = m.getmute()
        return mute_vals[0] == 1  # 1 = muted

    def set_mute(self, muted: bool):
        """Set mute state."""
        m = self._mixer(CTRL_EXT_SWITCH)
        m.setmute(1 if muted else 0)

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

    def get_mix(self) -> int:
        """Get monitor mix ratio (0=input only, 100=playback only).

        Uses Mixer Unit 60 via kernel module if available, otherwise
        approximates from volume/gain ratio.
        """
        if self._has_kmod():
            try:
                return self._kmod_get_mix()
            except Exception as e:
                log.warning("kmod mix read failed, using fallback: %s", e)

        log.warning("not using kmod")
        # Fallback: approximate from volume/gain balance
        out_vols = self.get_volume()
        in_gains = self.get_gain()
        avg_out = sum(out_vols[:2]) / min(len(out_vols), 2)
        avg_in = sum(in_gains[:2]) / min(len(in_gains), 2)
        total = avg_out + avg_in
        if total == 0:
            return 50
        return round(100 * avg_out / total)

    def set_mix(self, ratio: int):
        """Set monitor mix ratio (0=input only, 100=playback only).

        Uses Mixer Unit 60 via kernel module if available, otherwise
        adjusts volume/gain as approximation.
        """
        if self._has_kmod():
            try:
                self._kmod_set_mix(ratio)
                return
            except Exception as e:
                log.warning("kmod mix write failed, using fallback: %s", e)

        # Fallback: adjust gain and volume proportionally
        self.set_gain(100 - ratio)
        self.set_volume(ratio)
