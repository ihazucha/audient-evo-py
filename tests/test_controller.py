"""Integration tests for EVO4 controller — requires a connected Audient EVO4.

Each test saves the current value, sets a new value, verifies it, then restores.
"""

import time
import pytest

from evo4.controller import EVO4Controller, _db_to_usb, _usb_to_db, _MIXER_DB_MIN, _MIXER_MAX_CN


@pytest.fixture(scope="module")
def evo():
    return EVO4Controller()


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


class TestVolumeCurve:
    def test_0_pct_is_min(self):
        db = EVO4Controller._vol_pct_to_db(0)
        assert db == pytest.approx(-96.0)

    def test_100_pct_is_max(self):
        db = EVO4Controller._vol_pct_to_db(100)
        assert db == pytest.approx(0.0)

    def test_50_pct_is_minus_20(self):
        db = EVO4Controller._vol_pct_to_db(50)
        assert db == pytest.approx(-20.0, abs=0.5)

    def test_monotonic(self):
        prev = -999
        for pct in range(0, 101):
            db = EVO4Controller._vol_pct_to_db(pct)
            assert db >= prev, f"Non-monotonic at {pct}%: {db} < {prev}"
            prev = db

    def test_pct_roundtrip(self):
        for pct in range(0, 101):
            db = EVO4Controller._vol_pct_to_db(pct)
            back = EVO4Controller._vol_db_to_pct(db)
            assert back == pct, f"Roundtrip failed: {pct} -> {db} dB -> {back}"

    def test_clamp_below_zero(self):
        assert EVO4Controller._vol_pct_to_db(-10) == EVO4Controller._vol_pct_to_db(0)

    def test_clamp_above_100(self):
        assert EVO4Controller._vol_pct_to_db(200) == EVO4Controller._vol_pct_to_db(100)


class TestGainCurve:
    def test_0_pct_is_minus_8(self):
        db = EVO4Controller._gain_pct_to_db(0)
        assert db == pytest.approx(-8.0)

    def test_100_pct_is_plus_50(self):
        db = EVO4Controller._gain_pct_to_db(100)
        assert db == pytest.approx(50.0)

    def test_linear(self):
        # 50% should be midpoint: (-8 + 50) / 2 = 21
        db = EVO4Controller._gain_pct_to_db(50)
        assert db == pytest.approx(21.0)

    def test_monotonic(self):
        prev = -999
        for pct in range(0, 101):
            db = EVO4Controller._gain_pct_to_db(pct)
            assert db >= prev
            prev = db

    def test_pct_roundtrip(self):
        for pct in range(0, 101):
            db = EVO4Controller._gain_pct_to_db(pct)
            back = EVO4Controller._gain_db_to_pct(db)
            assert back == pct, f"Roundtrip failed: {pct} -> {db} dB -> {back}"


# --- Hardware integration tests ---

class TestVolume:
    def test_set_and_get_all_channels(self, evo):
        original = evo.get_volume()
        target = 42 if original[0] != 42 else 43

        try:
            evo.set_volume(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_volume()
            for ch, val in enumerate(result):
                assert abs(val - target) <= 1, \
                    f"Volume ch{ch}: expected ~{target}, got {val}"
        finally:
            for ch, val in enumerate(original):
                evo.set_volume(val, channel=ch + 1)

    def test_set_and_get_single_channel(self, evo):
        original = evo.get_volume()
        ch = 1
        target = 37 if original[ch - 1] != 37 else 38

        try:
            evo.set_volume(target, channel=ch)
            time.sleep(SETTLE_TIME)
            result = evo.get_volume()
            assert abs(result[ch - 1] - target) <= 1, \
                f"Volume ch{ch}: expected ~{target}, got {result[ch - 1]}"
        finally:
            evo.set_volume(original[ch - 1], channel=ch)

    def test_volume_boundaries(self, evo):
        original = evo.get_volume()
        try:
            for target in (0, 100):
                evo.set_volume(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_volume()
                for ch, val in enumerate(result):
                    assert val == target, \
                        f"Volume ch{ch} at boundary {target}: got {val}"
        finally:
            for ch, val in enumerate(original):
                evo.set_volume(val, channel=ch + 1)

    def test_set_returns_raw_and_db(self, evo):
        original = evo.get_volume()
        try:
            raw, db = evo.set_volume(50)
            assert isinstance(raw, int)
            assert isinstance(db, float)
            assert db == pytest.approx(-20.0, abs=0.5)
        finally:
            for ch, val in enumerate(original):
                evo.set_volume(val, channel=ch + 1)

    def test_debug_format(self, evo):
        debug = evo.get_volume_debug()
        assert len(debug) == 2
        for pct, raw, db in debug:
            assert isinstance(pct, int)
            assert isinstance(raw, int)
            assert isinstance(db, float)
            assert 0 <= pct <= 100


class TestGain:
    def test_set_and_get_all_channels(self, evo):
        original = evo.get_gain()
        target = 55 if original[0] != 55 else 56

        try:
            evo.set_gain(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_gain()
            for ch, val in enumerate(result):
                assert abs(val - target) <= 1, \
                    f"Gain ch{ch}: expected ~{target}, got {val}"
        finally:
            for ch, val in enumerate(original):
                evo.set_gain(val, channel=ch + 1)

    def test_set_and_get_single_channel(self, evo):
        original = evo.get_gain()
        ch = 1
        target = 30 if original[ch - 1] != 30 else 31

        try:
            evo.set_gain(target, channel=ch)
            time.sleep(SETTLE_TIME)
            result = evo.get_gain()
            assert abs(result[ch - 1] - target) <= 1, \
                f"Gain ch{ch}: expected ~{target}, got {result[ch - 1]}"
        finally:
            evo.set_gain(original[ch - 1], channel=ch)

    def test_per_channel_independence(self, evo):
        original = evo.get_gain()
        try:
            evo.set_gain(10, channel=1)
            evo.set_gain(90, channel=2)
            time.sleep(SETTLE_TIME)
            result = evo.get_gain()
            assert abs(result[0] - 10) <= 1, f"Ch1: expected ~10, got {result[0]}"
            assert abs(result[1] - 90) <= 1, f"Ch2: expected ~90, got {result[1]}"
        finally:
            for ch, val in enumerate(original):
                evo.set_gain(val, channel=ch + 1)

    def test_gain_boundaries(self, evo):
        original = evo.get_gain()
        try:
            for target in (0, 100):
                evo.set_gain(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_gain()
                for ch, val in enumerate(result):
                    assert val == target, \
                        f"Gain ch{ch} at boundary {target}: got {val}"
        finally:
            for ch, val in enumerate(original):
                evo.set_gain(val, channel=ch + 1)

    def test_set_returns_raw_and_db(self, evo):
        original = evo.get_gain()
        try:
            raw, db = evo.set_gain(0)
            assert db == pytest.approx(-8.0)
            raw, db = evo.set_gain(100)
            assert db == pytest.approx(50.0)
        finally:
            for ch, val in enumerate(original):
                evo.set_gain(val, channel=ch + 1)

    def test_debug_format(self, evo):
        debug = evo.get_gain_debug()
        assert len(debug) == 2
        for pct, raw, db in debug:
            assert isinstance(pct, int)
            assert isinstance(raw, int)
            assert isinstance(db, float)
            assert 0 <= pct <= 100


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


class TestMix:
    def test_set_and_get(self, evo):
        original = evo.get_mix()
        target = 65 if original != 65 else 66

        try:
            evo.set_mix(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_mix()
            assert abs(result - target) <= 1, \
                f"Mix: expected ~{target}, got {result}"
        finally:
            evo.set_mix(original)

    def test_mix_boundaries(self, evo):
        original = evo.get_mix()
        try:
            for target in (0, 100):
                evo.set_mix(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_mix()
                assert abs(result - target) <= 1, \
                    f"Mix at boundary {target}: got {result}"
        finally:
            evo.set_mix(original)

    def test_mix_midpoint(self, evo):
        original = evo.get_mix()
        try:
            evo.set_mix(50)
            time.sleep(SETTLE_TIME)
            result = evo.get_mix()
            assert abs(result - 50) <= 1
        finally:
            evo.set_mix(original)

    def test_mix_returns_int(self, evo):
        result = evo.get_mix()
        assert isinstance(result, int)
        assert 0 <= result <= 100


# --- Pan law unit tests (no hardware) ---

class TestPanLaw:
    def test_center_minus_3db(self):
        """At center pan, both channels should be volume - 3.01 dB."""
        for vol in [0.0, -6.0, -20.0, -60.0]:
            l, r = EVO4Controller._pan_to_lr_db(vol, 0.0)
            assert l == pytest.approx(vol - 3.0103, abs=0.01), f"Left at center, vol={vol}"
            assert r == pytest.approx(vol - 3.0103, abs=0.01), f"Right at center, vol={vol}"

    def test_full_left(self):
        """Full left: left = volume, right = -128 dB (silence)."""
        l, r = EVO4Controller._pan_to_lr_db(0.0, -100.0)
        assert l == pytest.approx(0.0, abs=0.01)
        assert r == _MIXER_DB_MIN

    def test_full_right(self):
        """Full right: left = -128 dB (silence), right = volume."""
        l, r = EVO4Controller._pan_to_lr_db(0.0, 100.0)
        assert l == _MIXER_DB_MIN
        assert r == pytest.approx(0.0, abs=0.01)

    def test_monotonic(self):
        """As pan goes left to right, left decreases and right increases."""
        pans = list(range(-100, 101, 5))
        lefts = []
        rights = []
        for p in pans:
            l, r = EVO4Controller._pan_to_lr_db(0.0, float(p))
            lefts.append(l)
            rights.append(r)
        for i in range(1, len(lefts)):
            assert lefts[i] <= lefts[i - 1] + 0.001, f"Left not monotonic at pan={pans[i]}"
            assert rights[i] >= rights[i - 1] - 0.001, f"Right not monotonic at pan={pans[i]}"

    def test_symmetric(self):
        """Pan law should be symmetric: L at pan=+X equals R at pan=-X."""
        for p in [25.0, 50.0, 75.0]:
            l_pos, r_pos = EVO4Controller._pan_to_lr_db(0.0, p)
            l_neg, r_neg = EVO4Controller._pan_to_lr_db(0.0, -p)
            assert l_pos == pytest.approx(r_neg, abs=0.01)
            assert r_pos == pytest.approx(l_neg, abs=0.01)

    def test_clamps_to_range(self):
        """Volume near silence should clamp to _MIXER_DB_MIN."""
        l, r = EVO4Controller._pan_to_lr_db(_MIXER_DB_MIN, 0.0)
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
            evo.set_mixer_crosspoint(_MIXER_MAX_CN, 0.0)
        with pytest.raises(ValueError):
            evo.set_mixer_crosspoint(-1, 0.0)

    def test_input_invalid_num(self, evo):
        with pytest.raises(ValueError):
            evo.set_mixer_input(3, 0.0)
