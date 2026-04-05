"""Integration tests for EVO4 controller - requires a connected Audient EVO4.

Each test saves the current value, sets a new value, verifies it, then restores.
"""

import time
import pytest

from evo.controller import EVOController, _db_to_usb, _usb_to_db, _MIXER_DB_MIN
from evo.devices import EVO4


@pytest.fixture(scope="module")
def evo():
    return EVOController(EVO4)


SETTLE_TIME = 0.05  # seconds to wait after SET before GET


# --- Conversion helpers ---

class TestDbConversions:
    def test_db_to_usb_zero(self):
        assert _db_to_usb(0.0) == 0x0000

    def test_db_to_usb_negative(self):
        # -1 dB = -256 in 1/256 steps = 0xFF00 as unsigned 16-bit
        assert _db_to_usb(-1.0) == 0xFF00

    def test_db_to_usb_min(self):
        # -127 dB → should not overflow 16-bit
        raw = _db_to_usb(-127.0)
        assert 0 <= raw <= 0xFFFF

    def test_usb_to_db_zero(self):
        assert _usb_to_db(0x0000) == 0.0

    def test_usb_to_db_negative(self):
        assert _usb_to_db(0xFF00) == -1.0

    def test_usb_to_db_large_negative(self):
        # 0x8080 → signed = -32640 → -127.5 dB
        assert _usb_to_db(0x8080) == pytest.approx(-127.5)

    def test_roundtrip(self):
        for db in [0.0, -1.0, -20.0, -96.0]:
            assert _usb_to_db(_db_to_usb(db)) == pytest.approx(db, abs=1/256)


# --- Hardware integration tests ---

class TestVolume:
    def test_set_and_get(self, evo):
        original = evo.get_volume()
        target = -20.0 if abs(original - (-20.0)) > 1.0 else -30.0

        try:
            evo.set_volume(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_volume()
            assert abs(result - target) <= 0.5, \
                f"Volume: expected ~{target} dB, got {result} dB"
        finally:
            evo.set_volume(original)

    def test_volume_boundaries(self, evo):
        original = evo.get_volume()
        try:
            for target in (-96.0, 0.0):
                evo.set_volume(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_volume()
                assert abs(result - target) <= 0.5, \
                    f"Volume at boundary {target} dB: got {result} dB"
        finally:
            evo.set_volume(original)

    def test_set_returns_raw_and_db(self, evo):
        original = evo.get_volume()
        try:
            raw, db = evo.set_volume(-20.0)
            assert isinstance(raw, int)
            assert isinstance(db, float)
            assert db == pytest.approx(-20.0, abs=0.5)
        finally:
            evo.set_volume(original)

    def test_debug_format(self, evo):
        raw, db = evo.get_volume_debug()
        assert isinstance(raw, int)
        assert isinstance(db, float)
        assert -96.0 <= db <= 0.0


class TestGain:
    @pytest.mark.parametrize("target", ["input1", "input2"])
    def test_set_and_get(self, evo, target):
        original = evo.get_gain(target)
        goal = 21.0 if abs(original - 21.0) > 1.0 else 10.0

        try:
            evo.set_gain(target, goal)
            time.sleep(SETTLE_TIME)
            result = evo.get_gain(target)
            assert abs(result - goal) <= 0.5, \
                f"Gain {target}: expected ~{goal} dB, got {result} dB"
        finally:
            evo.set_gain(target, original)

    def test_per_input_independence(self, evo):
        orig1 = evo.get_gain("input1")
        orig2 = evo.get_gain("input2")
        try:
            evo.set_gain("input1", -5.0)
            evo.set_gain("input2", 30.0)
            time.sleep(SETTLE_TIME)
            r1 = evo.get_gain("input1")
            r2 = evo.get_gain("input2")
            assert abs(r1 - (-5.0)) <= 0.5, f"input1: expected ~-5 dB, got {r1}"
            assert abs(r2 - 30.0) <= 0.5, f"input2: expected ~30 dB, got {r2}"
        finally:
            evo.set_gain("input1", orig1)
            evo.set_gain("input2", orig2)

    @pytest.mark.parametrize("target", ["input1", "input2"])
    def test_gain_boundaries(self, evo, target):
        original = evo.get_gain(target)
        try:
            for goal in (-8.0, 50.0):
                evo.set_gain(target, goal)
                time.sleep(SETTLE_TIME)
                result = evo.get_gain(target)
                assert abs(result - goal) <= 0.5, \
                    f"Gain {target} at boundary {goal} dB: got {result} dB"
        finally:
            evo.set_gain(target, original)

    def test_set_returns_raw_and_db(self, evo):
        original = evo.get_gain("input1")
        try:
            _, db = evo.set_gain("input1", -8.0)
            assert db == pytest.approx(-8.0)
            _, db = evo.set_gain("input1", 50.0)
            assert db == pytest.approx(50.0)
        finally:
            evo.set_gain("input1", original)

    @pytest.mark.parametrize("target", ["input1", "input2"])
    def test_debug_format(self, evo, target):
        raw, db = evo.get_gain_debug(target)
        assert isinstance(raw, int)
        assert isinstance(db, float)
        assert -8.0 <= db <= 50.0


class TestMute:
    @pytest.mark.parametrize("target", ["input1", "input2", "output"])
    def test_toggle_mute(self, evo, target):
        original = evo.get_mute(target)
        new_state = not original

        try:
            evo.set_mute(target, new_state)
            time.sleep(SETTLE_TIME)
            result = evo.get_mute(target)
            assert result == new_state, \
                f"Mute {target}: expected {new_state}, got {result}"
        finally:
            evo.set_mute(target, original)

    @pytest.mark.parametrize("target", ["input1", "input2", "output"])
    def test_mute_on_off(self, evo, target):
        """Explicitly test both on and off states."""
        original = evo.get_mute(target)
        try:
            evo.set_mute(target, True)
            time.sleep(SETTLE_TIME)
            assert evo.get_mute(target) is True, f"{target} should be muted"

            evo.set_mute(target, False)
            time.sleep(SETTLE_TIME)
            assert evo.get_mute(target) is False, f"{target} should be unmuted"
        finally:
            evo.set_mute(target, original)

    def test_mute_targets_independent(self, evo):
        """Muting one target should not affect others."""
        originals = {t: evo.get_mute(t) for t in ["input1", "input2", "output"]}
        try:
            # Unmute all first
            for t in originals:
                evo.set_mute(t, False)
            time.sleep(SETTLE_TIME)

            # Mute only input1
            evo.set_mute("input1", True)
            time.sleep(SETTLE_TIME)

            assert evo.get_mute("input1") is True
            assert evo.get_mute("input2") is False
            assert evo.get_mute("output") is False
        finally:
            for t, val in originals.items():
                evo.set_mute(t, val)

    def test_invalid_target(self, evo):
        with pytest.raises(KeyError):
            evo.get_mute("nonexistent")
        with pytest.raises(KeyError):
            evo.set_mute("nonexistent", True)


class TestPhantom:
    @pytest.mark.parametrize("target", ["input1", "input2"])
    def test_toggle_phantom(self, evo, target):
        original = evo.get_phantom(target)
        new_state = not original

        try:
            evo.set_phantom(target, new_state)
            time.sleep(SETTLE_TIME)
            result = evo.get_phantom(target)
            assert result == new_state, \
                f"Phantom {target}: expected {new_state}, got {result}"
        finally:
            evo.set_phantom(target, original)

    @pytest.mark.parametrize("target", ["input1", "input2"])
    def test_phantom_on_off(self, evo, target):
        """Explicitly test both on and off states."""
        original = evo.get_phantom(target)
        try:
            evo.set_phantom(target, True)
            time.sleep(SETTLE_TIME)
            assert evo.get_phantom(target) is True, f"{target} phantom should be on"

            evo.set_phantom(target, False)
            time.sleep(SETTLE_TIME)
            assert evo.get_phantom(target) is False, f"{target} phantom should be off"
        finally:
            evo.set_phantom(target, original)

    def test_phantom_targets_independent(self, evo):
        """Setting phantom on one input should not affect the other."""
        originals = {t: evo.get_phantom(t) for t in ["input1", "input2"]}
        try:
            evo.set_phantom("input1", False)
            evo.set_phantom("input2", False)
            time.sleep(SETTLE_TIME)

            evo.set_phantom("input1", True)
            time.sleep(SETTLE_TIME)

            assert evo.get_phantom("input1") is True
            assert evo.get_phantom("input2") is False
        finally:
            for t, val in originals.items():
                evo.set_phantom(t, val)

    def test_invalid_target(self, evo):
        with pytest.raises(KeyError):
            evo.get_phantom("nonexistent")
        with pytest.raises(KeyError):
            evo.set_phantom("nonexistent", True)


class TestMonitor:
    def test_set_and_get(self, evo):
        original = evo.get_monitor()
        target = 65 if original != 65 else 66

        try:
            evo.set_monitor(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_monitor()
            assert abs(result - target) <= 1, \
                f"Monitor: expected ~{target}, got {result}"
        finally:
            evo.set_monitor(original)

    def test_monitor_boundaries(self, evo):
        original = evo.get_monitor()
        try:
            for target in (0, 100):
                evo.set_monitor(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_monitor()
                assert abs(result - target) <= 1, \
                    f"Monitor at boundary {target}: got {result}"
        finally:
            evo.set_monitor(original)

    def test_monitor_midpoint(self, evo):
        original = evo.get_monitor()
        try:
            evo.set_monitor(50)
            time.sleep(SETTLE_TIME)
            result = evo.get_monitor()
            assert abs(result - 50) <= 1
        finally:
            evo.set_monitor(original)

    def test_monitor_returns_int(self, evo):
        result = evo.get_monitor()
        assert isinstance(result, int)
        assert 0 <= result <= 100


# --- Pan law unit tests (no hardware) ---

class TestPanLaw:
    def test_center_minus_3db(self):
        """At center pan, both channels should be volume - 3.01 dB."""
        for vol in [0.0, -6.0, -20.0, -60.0]:
            l, r = EVOController._pan_to_lr_db(vol, 0.0)
            assert l == pytest.approx(vol - 3.0103, abs=0.01), f"Left at center, vol={vol}"
            assert r == pytest.approx(vol - 3.0103, abs=0.01), f"Right at center, vol={vol}"

    def test_full_left(self):
        """Full left: left = volume, right = -128 dB (silence)."""
        l, r = EVOController._pan_to_lr_db(0.0, -100.0)
        assert l == pytest.approx(0.0, abs=0.01)
        assert r == _MIXER_DB_MIN

    def test_full_right(self):
        """Full right: left = -128 dB (silence), right = volume."""
        l, r = EVOController._pan_to_lr_db(0.0, 100.0)
        assert l == _MIXER_DB_MIN
        assert r == pytest.approx(0.0, abs=0.01)

    def test_monotonic(self):
        """As pan goes left to right, left decreases and right increases."""
        pans = list(range(-100, 101, 5))
        lefts = []
        rights = []
        for p in pans:
            l, r = EVOController._pan_to_lr_db(0.0, float(p))
            lefts.append(l)
            rights.append(r)
        for i in range(1, len(lefts)):
            assert lefts[i] <= lefts[i - 1] + 0.001, f"Left not monotonic at pan={pans[i]}"
            assert rights[i] >= rights[i - 1] - 0.001, f"Right not monotonic at pan={pans[i]}"

    def test_symmetric(self):
        """Pan law should be symmetric: L at pan=+X equals R at pan=-X."""
        for p in [25.0, 50.0, 75.0]:
            l_pos, r_pos = EVOController._pan_to_lr_db(0.0, p)
            l_neg, r_neg = EVOController._pan_to_lr_db(0.0, -p)
            assert l_pos == pytest.approx(r_neg, abs=0.01)
            assert r_pos == pytest.approx(l_neg, abs=0.01)

    def test_clamps_to_range(self):
        """Volume near silence should clamp to _MIXER_DB_MIN."""
        l, r = EVOController._pan_to_lr_db(_MIXER_DB_MIN, 0.0)
        assert l == _MIXER_DB_MIN
        assert r == _MIXER_DB_MIN


# --- Mixer integration tests (hardware) ---

class TestMixer:
    def test_set_crosspoint(self, evo):
        """Set CN=0 to 0 dB — should not error."""
        evo.set_mixer_crosspoint(0, 0.0)

    def test_get_crosspoint_stall(self, evo):
        """GET_CUR on MU60 is expected to STALL (write-only)."""
        try:
            db = evo.get_mixer_crosspoint(0)
            # If it succeeds, that's fine too
            assert isinstance(db, float)
        except OSError:
            pass  # expected STALL

    def test_set_mixer_input(self, evo):
        """Set input1 to 0 dB center — should not error."""
        evo.set_mixer_input(1, 0.0, 0.0)

    def test_set_mixer_output(self, evo):
        """Set output to 0 dB with default pans — should not error."""
        evo.set_mixer_output(0.0)

    def test_set_mixer_loopback(self, evo):
        """Set loopback to -6 dB with default pans — should not error."""
        evo.set_mixer_loopback(-6.0)

    def test_crosspoint_invalid_cn(self, evo):
        with pytest.raises(ValueError):
            evo.set_mixer_crosspoint(evo._mixer_max_cn, 0.0)
        with pytest.raises(ValueError):
            evo.set_mixer_crosspoint(-1, 0.0)

    def test_input_invalid_num(self, evo):
        with pytest.raises(ValueError):
            evo.set_mixer_input(evo.spec.num_inputs + 1, 0.0)
