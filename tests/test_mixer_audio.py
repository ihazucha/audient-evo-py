"""Audio loopback tests for EVO4 mixer — requires connected hardware.

Tests the MU60 loopback mixer by playing known signals through DAW output,
configuring mixer crosspoints, and capturing/analyzing the loopback return.

Signal path under test:
  Python → PipeWire → EVO4 DAW Out (CH1/2) → MU60 crosspoints → Loopback In (CH3/4) → PipeWire → Python

Requirements:
  - EVO4 connected and evo4_raw kmod loaded
  - PipeWire running with EVO4 sinks/sources available
  - No other audio playing through EVO4 during tests
  - pip: sounddevice, numpy
"""

import time

import numpy as np
import pytest
import sounddevice as sd

from evo.controller import EVOController, _MIXER_DB_MIN
from evo.devices import EVO4

# ── Audio constants ──────────────────────────────────────────────────

SAMPLE_RATE = 48000
TONE_HZ = 1000.0
DURATION = 1.0          # seconds of playback + capture
TRIM = 0.25             # seconds trimmed from each end to skip latency transients

# dBFS thresholds for signal detection
PRESENT = -40.0         # above → signal present
ABSENT = -60.0          # below → considered silent


# ── Helpers ──────────────────────────────────────────────────────────

def _find_device(name, kind):
    """Find sounddevice index by exact device description and 'input'/'output'.

    Device names from sounddevice look like 'EVO4 Main Output, JACK Audio ...',
    so we match the part before the first comma.
    """
    key = f"max_{kind}_channels"
    for i, d in enumerate(sd.query_devices()):
        desc = d["name"].split(",")[0]
        if desc == name and d[key] > 0:
            return i
    raise RuntimeError(f"No {kind} device named '{name}'")


def sine(freq=TONE_HZ, duration=DURATION):
    """Mono float32 sine at 90% amplitude."""
    t = np.arange(int(SAMPLE_RATE * duration), dtype=np.float32) / SAMPLE_RATE
    return np.float32(0.9) * np.sin(np.float32(2 * np.pi * freq) * t)


def stereo(mono, *, left=True, right=True):
    """Pack mono into a 2-channel array, optionally silencing a side."""
    out = np.zeros((len(mono), 2), dtype=np.float32)
    if left:
        out[:, 0] = mono
    if right:
        out[:, 1] = mono
    return out


def rms_dbfs(signal):
    """RMS in dBFS. Returns -120 for digital silence."""
    rms = np.sqrt(np.mean(signal.astype(np.float64) ** 2))
    return 20.0 * np.log10(max(rms, 1e-12))


def trim(captured):
    """Strip leading/trailing samples to avoid latency and fade transients."""
    n = int(TRIM * SAMPLE_RATE)
    return captured[n:-n] if len(captured) > 2 * n else captured


def levels(captured):
    """Return (left_dBFS, right_dBFS) from stereo capture, after trimming."""
    t = trim(captured)
    return rms_dbfs(t[:, 0]), rms_dbfs(t[:, 1])


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def evo():
    return EVOController(EVO4)


@pytest.fixture(scope="module")
def daw_out():
    """EVO4 Main Output sink — plays to DAW CH1/2."""
    return _find_device("EVO4 Main Output", "output")


@pytest.fixture(scope="module")
def loop_out():
    """EVO4 Loopback Output sink — plays to Loopback Out CH3/4."""
    return _find_device("EVO4 Loopback Output", "output")


@pytest.fixture(scope="module")
def loop_cap():
    """EVO4 Loopback capture source — records Loopback In CH3/4."""
    return _find_device("EVO4 Loopback", "input")


@pytest.fixture(autouse=True)
def silence_all_crosspoints(evo):
    """Mute every crosspoint before and after each test."""
    def _silence():
        for cn in range(12):
            evo.set_mixer_crosspoint(cn, _MIXER_DB_MIN)
        time.sleep(0.05)
    _silence()
    yield
    _silence()


SETTLE = 0.1  # seconds after mixer changes before starting audio


def playrec(signal, capture_dev, playback_dev):
    """Simultaneous play + record via sounddevice. Returns captured ndarray."""
    time.sleep(SETTLE)
    # Pad to full duration if shorter
    needed = int(SAMPLE_RATE * DURATION)
    if len(signal) < needed:
        pad = np.zeros((needed, signal.shape[1]), dtype=np.float32)
        pad[:len(signal)] = signal
        signal = pad

    captured = sd.playrec(
        signal,
        samplerate=SAMPLE_RATE,
        channels=2,
        device=(capture_dev, playback_dev),
        dtype="float32",
    )
    sd.wait()
    return captured


# ── Tests: baseline ──────────────────────────────────────────────────

class TestBaseline:
    """All crosspoints silenced — loopback must be quiet."""

    def test_silence(self, daw_out, loop_cap):
        """Playing audio with all crosspoints muted → loopback silent."""
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left not silent: {l:.1f} dBFS"
        assert r < ABSENT, f"Right not silent: {r:.1f} dBFS"


# ── Tests: individual crosspoint routing ─────────────────────────────

class TestDawCrosspoints:
    """Verify each DAW→Loopback crosspoint routes to the correct channel."""

    def test_daw_l_to_loop_l(self, evo, daw_out, loop_cap):
        """CN 4: DAW L → Loopback L only."""
        evo.set_mixer_crosspoint(4, 0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_daw_l_to_loop_r(self, evo, daw_out, loop_cap):
        """CN 5: DAW L → Loopback R only."""
        evo.set_mixer_crosspoint(5, 0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_daw_r_to_loop_l(self, evo, daw_out, loop_cap):
        """CN 6: DAW R → Loopback L only."""
        evo.set_mixer_crosspoint(6, 0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_daw_r_to_loop_r(self, evo, daw_out, loop_cap):
        """CN 7: DAW R → Loopback R only."""
        evo.set_mixer_crosspoint(7, 0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_stereo_passthrough(self, evo, daw_out, loop_cap):
        """CN 4+7: DAW stereo → Loopback stereo."""
        evo.set_mixer_crosspoint(4, 0.0)   # DAW L → Loop L
        evo.set_mixer_crosspoint(7, 0.0)   # DAW R → Loop R
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_cross_routing(self, evo, daw_out, loop_cap):
        """CN 5+6: DAW L→Loop R, DAW R→Loop L (swap channels)."""
        evo.set_mixer_crosspoint(5, 0.0)   # DAW L → Loop R
        evo.set_mixer_crosspoint(6, 0.0)   # DAW R → Loop L
        # Play left only — should appear on right only
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"


# ── Tests: loopback output routing (CH3/4 → loopback capture) ───────

class TestLoopbackCrosspoints:
    """Verify Loopback Out → Loopback In crosspoint routing (CN 8-11)."""

    def test_loopout_l_to_loop_l(self, evo, loop_out, loop_cap):
        """CN 8: Loopback Out L → Loopback In L."""
        evo.set_mixer_crosspoint(8, 0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_loopout_r_to_loop_r(self, evo, loop_out, loop_cap):
        """CN 11: Loopback Out R → Loopback In R."""
        evo.set_mixer_crosspoint(11, 0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_loopout_stereo(self, evo, loop_out, loop_cap):
        """CN 8+11: Loopback Out stereo → Loopback In stereo."""
        evo.set_mixer_crosspoint(8, 0.0)
        evo.set_mixer_crosspoint(11, 0.0)
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"


# ── Tests: convenience methods ───────────────────────────────────────

class TestMixerOutput:
    """Test set_mixer_output() high-level routing."""

    def test_default_stereo(self, evo, daw_out, loop_cap):
        """Default pans (L=-100, R=+100) produce clean L/R separation."""
        evo.set_mixer_output(0.0)
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left: {l:.1f} dBFS"
        assert r > PRESENT, f"Right: {r:.1f} dBFS"

    def test_left_only_playback(self, evo, daw_out, loop_cap):
        """With default stereo routing, left-only playback → left-only loopback."""
        evo.set_mixer_output(0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"

    def test_right_only_playback(self, evo, daw_out, loop_cap):
        """With default stereo routing, right-only playback → right-only loopback."""
        evo.set_mixer_output(0.0)
        sig = stereo(sine(), left=False, right=True)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l < ABSENT, f"Left should be silent: {l:.1f} dBFS"
        assert r > PRESENT, f"Right should have signal: {r:.1f} dBFS"

    def test_center_pan_spreads_mono(self, evo, daw_out, loop_cap):
        """Center pan for DAW L: left-only signal appears on both loopback channels equally."""
        evo.set_mixer_output(0.0, pan_l=0.0, pan_r=0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left: {l:.1f} dBFS"
        assert r > PRESENT, f"Right: {r:.1f} dBFS"
        assert abs(l - r) < 3.0, f"Channels should be ~equal: L={l:.1f}, R={r:.1f} dBFS"


class TestMixerLoopback:
    """Test set_mixer_loopback() high-level routing."""

    def test_default_stereo(self, evo, loop_out, loop_cap):
        """Default pans produce stereo loopback-to-loopback routing."""
        evo.set_mixer_loopback(0.0)
        sig = stereo(sine(), left=True, right=True)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left: {l:.1f} dBFS"
        assert r > PRESENT, f"Right: {r:.1f} dBFS"

    def test_left_only(self, evo, loop_out, loop_cap):
        """Left-only loopback out → left-only loopback capture."""
        evo.set_mixer_loopback(0.0)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, loop_out)
        l, r = levels(cap)
        assert l > PRESENT, f"Left should have signal: {l:.1f} dBFS"
        assert r < ABSENT, f"Right should be silent: {r:.1f} dBFS"


# ── Tests: gain / volume behavior ────────────────────────────────────

class TestMixerGain:
    """Verify crosspoint gain affects captured level correctly."""

    def _measure_at_gain(self, evo, daw_out, loop_cap, gain_db):
        """Set CN4 to gain_db, play left sine, return left channel dBFS."""
        evo.set_mixer_crosspoint(4, gain_db)
        time.sleep(0.05)
        sig = stereo(sine(), left=True, right=False)
        cap = playrec(sig, loop_cap, daw_out)
        return rms_dbfs(trim(cap)[:, 0])

    def test_gain_ordering(self, evo, daw_out, loop_cap):
        """Higher crosspoint gain → louder capture."""
        lev_0 = self._measure_at_gain(evo, daw_out, loop_cap, 0.0)
        lev_12 = self._measure_at_gain(evo, daw_out, loop_cap, -12.0)
        lev_24 = self._measure_at_gain(evo, daw_out, loop_cap, -24.0)
        assert lev_0 > lev_12 > lev_24, \
            f"Levels should decrease: 0dB={lev_0:.1f}, -12dB={lev_12:.1f}, -24dB={lev_24:.1f}"

    def test_6db_step(self, evo, daw_out, loop_cap):
        """0 dB vs -6 dB crosspoint should differ by ~6 dB in capture."""
        lev_0 = self._measure_at_gain(evo, daw_out, loop_cap, 0.0)
        lev_6 = self._measure_at_gain(evo, daw_out, loop_cap, -6.0)
        diff = lev_0 - lev_6
        assert 3.0 < diff < 9.0, \
            f"Expected ~6 dB difference, got {diff:.1f} (0dB={lev_0:.1f}, -6dB={lev_6:.1f})"

    def test_silence_at_min_gain(self, evo, daw_out, loop_cap):
        """Crosspoint at -128 dB should produce silence."""
        lev = self._measure_at_gain(evo, daw_out, loop_cap, _MIXER_DB_MIN)
        assert lev < ABSENT, f"Should be silent at min gain: {lev:.1f} dBFS"


# ── Tests: summation (multiple crosspoints active) ───────────────────

class TestMixerSummation:
    """Verify that multiple active crosspoints sum into the loopback bus."""

    def test_both_daw_channels_sum_to_mono(self, evo, daw_out, loop_cap):
        """DAW L + DAW R both routed to Loopback L — level should be higher than one alone."""
        sig = stereo(sine(), left=True, right=True)

        # Single source
        evo.set_mixer_crosspoint(4, 0.0)   # DAW L → Loop L
        cap_single = playrec(sig, loop_cap, daw_out)
        lev_single = rms_dbfs(trim(cap_single)[:, 0])

        # Both sources
        for cn in range(12):
            evo.set_mixer_crosspoint(cn, _MIXER_DB_MIN)
        evo.set_mixer_crosspoint(4, 0.0)   # DAW L → Loop L
        evo.set_mixer_crosspoint(6, 0.0)   # DAW R → Loop L
        cap_both = playrec(sig, loop_cap, daw_out)
        lev_both = rms_dbfs(trim(cap_both)[:, 0])

        # Two correlated sources at 0dB should sum to ~+6dB (voltage doubling)
        diff = lev_both - lev_single
        assert 2.0 < diff < 9.0, \
            f"Sum should be louder: single={lev_single:.1f}, both={lev_both:.1f}, diff={diff:.1f} dB"
