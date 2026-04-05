"""Interactive mic input → loopback mixer tests — requires a connected microphone.

Tests the MU60 input crosspoints (CN 0-3) by asking the user to make sound
into a physical mic, then verifying the signal appears on the correct
loopback channel(s) based on pan setting.

Signal path under test:
  Microphone → EVO4 Input 1/2 → MU60 crosspoints (CN 0-3) → Loopback In (CH3/4) → PipeWire → Python

Run with:  pytest tests/test_mixer_mic.py -s
The -s flag is required so interactive prompts are visible.

Requirements:
  - EVO4 connected and evo4_raw kmod loaded
  - PipeWire running with EVO4 sinks/sources available
  - A microphone connected to Input 1 or Input 2
  - pip: sounddevice, numpy
"""

import time

import numpy as np
import pytest
import sounddevice as sd

from evo.controller import EVOController, _MIXER_DB_MIN
from evo.devices import EVO4

SAMPLE_RATE = 48000
CAPTURE_DURATION = 3.0      # seconds to capture while user makes noise
SETTLE = 0.1                # seconds after mixer changes before capture

# dBFS thresholds (looser than automated tests — analog path adds loss/noise)
PRESENT = -50.0
ABSENT = -60.0


def _find_device(name, kind):
    """Find sounddevice index by exact device description and 'input'/'output'."""
    key = f"max_{kind}_channels"
    for i, d in enumerate(sd.query_devices()):
        desc = d["name"].split(",")[0]
        if desc == name and d[key] > 0:
            return i
    raise RuntimeError(f"No {kind} device named '{name}'")


def rms_dbfs(signal):
    """RMS in dBFS. Returns -120 for digital silence."""
    rms = np.sqrt(np.mean(signal.astype(np.float64) ** 2))
    return 20.0 * np.log10(max(rms, 1e-12))


def trim(captured, trim_s=0.25):
    """Strip leading/trailing samples to avoid transients."""
    n = int(trim_s * SAMPLE_RATE)
    return captured[n:-n] if len(captured) > 2 * n else captured


def levels(captured):
    """Return (left_dBFS, right_dBFS) from stereo capture, after trimming."""
    t = trim(captured)
    return rms_dbfs(t[:, 0]), rms_dbfs(t[:, 1])


def capture_loopback(loop_cap):
    """Record from loopback capture source."""
    frames = int(SAMPLE_RATE * CAPTURE_DURATION)
    cap = sd.rec(frames, samplerate=SAMPLE_RATE, channels=2,
                 device=loop_cap, dtype="float32")
    sd.wait()
    return cap


def prompt_and_capture(pan_desc, loop_cap):
    """Prompt user to make noise, capture loopback, return levels."""
    input(f"\n  Ready to test pan={pan_desc}."
          f" Make continuous sound into the mic, then press Enter...")
    print(f"  Capturing {CAPTURE_DURATION:.0f}s — keep making sound...")
    cap = capture_loopback(loop_cap)
    l, r = levels(cap)
    print(f"  Captured levels: L={l:.1f} dBFS, R={r:.1f} dBFS")
    return l, r


@pytest.fixture(scope="module")
def evo():
    return EVOController(EVO4)


@pytest.fixture(scope="module")
def loop_cap():
    return _find_device("EVO4 Loopback", "input")


@pytest.fixture(scope="module")
def input_num():
    """Ask the user which input has a mic connected."""
    print()
    while True:
        ans = input("Which input has a mic connected? [1/2]: ").strip()
        if ans in ("1", "2"):
            return int(ans)
        print("Please enter 1 or 2.")


@pytest.fixture(autouse=True)
def silence_all_crosspoints(evo):
    """Silence all crosspoints before and after each test."""
    def _silence():
        for cn in range(12):
            evo.set_mixer_crosspoint(cn, _MIXER_DB_MIN)
        time.sleep(0.05)
    _silence()
    yield
    _silence()


class TestMicInput:
    """Verify mic/line input routing through MU60 at different pan positions."""

    def test_pan_full_left(self, evo, input_num, loop_cap):
        """Pan=-100: input should appear on loopback LEFT only."""
        evo.set_mixer_input(input_num, 0.0, pan=-100.0)
        time.sleep(SETTLE)
        l, r = prompt_and_capture("-100 (full left)", loop_cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_pan_center(self, evo, input_num, loop_cap):
        """Pan=0: input should appear on BOTH loopback channels equally."""
        evo.set_mixer_input(input_num, 0.0, pan=0.0)
        time.sleep(SETTLE)
        l, r = prompt_and_capture("0 (center)", loop_cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"
        assert abs(l - r) < 6.0, \
            f"Channels should be roughly equal: L={l:.1f}, R={r:.1f} dBFS"

    def test_pan_full_right(self, evo, input_num, loop_cap):
        """Pan=+100: input should appear on loopback RIGHT only."""
        evo.set_mixer_input(input_num, 0.0, pan=100.0)
        time.sleep(SETTLE)
        l, r = prompt_and_capture("+100 (full right)", loop_cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"
