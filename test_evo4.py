"""Integration tests for EVO4 controller — requires a connected Audient EVO4.

Each test saves the current value, sets a new value, verifies it, then restores.
"""

import time
import pytest

from evo4_alsa import EVO4Controller


@pytest.fixture(scope="module")
def evo():
    return EVO4Controller()


SETTLE_TIME = 0.05  # seconds to wait after SET before GET


class TestVolume:
    def test_set_and_get_all_channels(self, evo):
        original = evo.get_volume()
        target = 42 if original[0] != 42 else 43

        try:
            evo.set_volume(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_volume()
            for ch, val in enumerate(result[:2]):
                assert val == target, f"Volume ch{ch}: expected {target}, got {val}"
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
            assert result[ch - 1] == target, \
                f"Volume ch{ch}: expected {target}, got {result[ch - 1]}"
        finally:
            evo.set_volume(original[ch - 1], channel=ch)

    def test_volume_boundaries(self, evo):
        original = evo.get_volume()
        try:
            for target in (0, 100):
                evo.set_volume(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_volume()
                for ch, val in enumerate(result[:2]):
                    assert val == target, \
                        f"Volume ch{ch} at boundary {target}: got {val}"
        finally:
            for ch, val in enumerate(original):
                evo.set_volume(val, channel=ch + 1)


class TestGain:
    def test_set_and_get_all_channels(self, evo):
        original = evo.get_gain()
        target = 55 if original[0] != 55 else 56

        try:
            evo.set_gain(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_gain()
            for ch, val in enumerate(result[:2]):
                assert val == target, f"Gain ch{ch}: expected {target}, got {val}"
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
            assert result[ch - 1] == target, \
                f"Gain ch{ch}: expected {target}, got {result[ch - 1]}"
        finally:
            evo.set_gain(original[ch - 1], channel=ch)

    def test_gain_boundaries(self, evo):
        original = evo.get_gain()
        try:
            for target in (0, 100):
                evo.set_gain(target)
                time.sleep(SETTLE_TIME)
                result = evo.get_gain()
                for ch, val in enumerate(result[:2]):
                    assert val == target, \
                        f"Gain ch{ch} at boundary {target}: got {val}"
        finally:
            for ch, val in enumerate(original):
                evo.set_gain(val, channel=ch + 1)


class TestMute:
    def test_toggle_mute(self, evo):
        original = evo.get_mute()
        target = not original

        try:
            evo.set_mute(target)
            time.sleep(SETTLE_TIME)
            result = evo.get_mute()
            assert result == target, f"Mute: expected {target}, got {result}"
        finally:
            evo.set_mute(original)


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
