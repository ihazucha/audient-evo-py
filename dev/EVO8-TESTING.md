# EVO 8 Testing Manual

Step-by-step verification of the EVO 8 implementation.
Ideally record terminal output at each step and send results back for analysis.
(make a folder or file, document what works and doesn't as per manual)

## 1. Prerequisites

- Audient EVO 8
- Linux with PipeWire + WirePlumber (0.5+)
- Kernel headers installed (`linux-headers` package)
- Python 3.10+
- `git clone` of this repo

## 2. Installation

### 2a. Kernel module

```bash
cd kmod
sudo ./install.sh
# Select EVO 8 when prompted
```

**Expected:** Module loads, `/dev/evo8` exists.

```bash
ls -la /dev/evo8
lsmod | grep evo_raw
```

Record output.

### 2b. evoctl (pipx)

```bash
pipx install .
```

**Expected:** `evoctl` and `evotui` commands available.

### 2c. WirePlumber config (not stricly neccessary but helpful - needed to automated mixer tests)

**MAKE BACKUPS OF YOUR CURRENT CONFIG**

```bash
bash wireplumber/install.sh
# Select EVO 8 when prompted
```

**Expected:** PipeWire restarts, EVO 8 set as default device.

```bash
wpctl status | grep -i evo
```

Record output.

## 3. Diagnostics Baseline

```bash
evoctl diag > diag.json
cat diag.json
```

Record the full JSON output.

## 4. Controls Testing

For each command below, record the terminal output.

### 4a. Volume - output pair 1

```bash
evoctl get volume
evoctl set volume -20
evoctl get volume
evoctl set volume -96
evoctl get volume
evoctl set volume 0
evoctl get volume
```

### 4b. Volume - output pair 2

```bash
evoctl get volume -t output2
evoctl set volume -20 -t output2
evoctl get volume -t output2
evoctl set volume 0 -t output2
```

### 4c. Gain - all 4 inputs

```bash
for i in input1 input2 input3 input4; do
  evoctl set gain 29 -t $i
  evoctl get gain -t $i
done
```

**Expected:** Each input reports ~29 dB independently.

### 4d. Gain boundaries

```bash
evoctl set gain 0 -t input1
evoctl get gain -t input1
evoctl set gain 58 -t input1
evoctl get gain -t input1
```

**Expected:** 0 dB and 58 dB (EVO 8 range).

### 4e. Mute - all 6 targets

```bash
for t in input1 input2 input3 input4 output1 output2; do
  evoctl set mute 1 -t $t
  evoctl get mute -t $t
  evoctl set mute 0 -t $t
  evoctl get mute -t $t
done
```

**Expected:** Each toggles independently. Muting output1 should not affect output2.

### 4f. Phantom power - all 4 inputs

**WARNING:** Only enable phantom if you have condenser mics or no mics connected. Phantom can damage ribbon mics.

```bash
for i in input1 input2 input3 input4; do
  evoctl set phantom 1 -t $i
  evoctl get phantom -t $i
  evoctl set phantom 0 -t $i
  evoctl get phantom -t $i
done
```

### 4g. Monitor (should fail)

```bash
evoctl set monitor 50
```

**Expected:** Error message - EVO 8 does not have direct monitor control.

## 5. Mixer Testing

### 5a. Basic crosspoint

```bash
evoctl mixer input1 --volume 0 --pan 0
evoctl mixer output --volume 0
evoctl mixer loopback --volume -128
```

**Expected:** No errors. Input 1 routed to loopback at center pan.

### 5b. Second mix bus

```bash
evoctl mixer input1 --volume 0 --pan 0 --mix-bus 1
evoctl mixer output --volume 0 --mix-bus 1
```

**Expected:** No errors. Routes to OUT 3/4 mix bus.

### 5c. All inputs

```bash
for i in 1 2 3 4; do
  evoctl mixer input$i --volume -6 --pan 0
done
```

## 6. Status

```bash
evoctl status
evoctl status -f json
```

Record both outputs. JSON should show all 4 inputs, both output pairs, no monitor field.

## 7. WirePlumber Verification

```bash
wpctl status
```

Record the full output. Look for:
- EVO 8 ALSA sink/source nodes
- Loopback virtual nodes (if configured)
- Default sink/source set to EVO 8

Play audio (e.g. `speaker-test -c 2 -t sine -l 1`) and confirm it comes through output 1/2.

## 8. Config Save/Load

```bash
evoctl set volume -30
evoctl set gain 25 -t input1
evoctl save
cat ~/.config/audient-evo-py/evo8/config.json

evoctl set volume -10
evoctl set gain 0 -t input1
evoctl load
evoctl status
```

**Expected:** After load, volume back to -30 dB, gain back to 25 dB.

## 9. Test Suite

```bash
pytest tests/test_controller.py -v --device evo8
```

Record the full output. All tests should pass or skip gracefully (monitor tests should skip).

**REQUIREMENTS**:
  - python `sounddevice` and `numpy` packages.
  - wireplumber config installed

```bash
pip install sounddevice numpy
# Mixer DAW testing - requires WirePlumber config installed
pytest tests/test_mixer_audio.py -v --device evo8
# Mixer INPUT testing - manual, gonna need mic connected to tested inputs and
# record 3 second long voice samples when requested
pytest tests/test_mixer_mic.py -vs --device evo8
```

## 10. Uninstall Verification

### 10a. WirePlumber

```bash
bash wireplumber/uninstall.sh
wpctl status | grep -i evo
```

**Expected:** EVO configs removed, PipeWire restarted.

### 10b. Kernel module

```bash
cd kmod
sudo ./uninstall.sh
ls -la /dev/evo8
```

**Expected:** Module removed, `/dev/evo8` gone.

### 10c. evoctl

```bash
pipx uninstall audient-evo-py
```

## Issue Report Template

If something fails, please include:

```
Kernel: (uname -r)
Distro: (cat /etc/os-release | head -2)
Python: (python --version)

Step failed: (number and name)
Command run: (exact command)
Expected: (what should have happened)
Actual: (what happened - paste terminal output)

Diagnostics: (attach diag.json)
```
