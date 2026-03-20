# Reverse Engineering Findings

Raw probe results from scanning the Audient EVO4's USB entities.
Gathered using `probe.py scan` and targeted GET/SET experiments.

## Methodology

1. Enumerated USB descriptors to identify entities (Feature Units, Extension
   Units, Mixer Unit) and their IDs
2. Sent GET_CUR with every CS (0-7) x CN (0-4) combination on each entity,
   testing both 2-byte and 4-byte payload lengths
3. For entities that responded: varied values with SET_CUR and observed effects
4. Blind SET_CUR scan on entities that STALL on GET_CUR (MU60, EU50, EU57)
5. Matched behavior to vendor app controls and cross-referenced with community
   projects (vijay-prema, Evo4mixer, evoctl, MixiD)

## USB Interfaces

| Interface | Class | Description |
|-----------|-------|-------------|
| 0 | Audio Control | All entities (FU10, FU11, EU50-59, MU60) |
| 1 | Audio Streaming | Output (playback) |
| 2 | Audio Streaming | Input (recording) |
| 3 | DFU | Device Firmware Update — claimed by evo4_raw kmod |

No HID interface. Front panel buttons/knob are internal to the device
microcontroller and not exposed as USB controls.

## Probe Results

wIndex = `(EntityID << 8) | Interface(0)`, wValue = `(CS << 8) | CN`.
All values little-endian. Extension Units use 4-byte payloads, Feature Units
use 2-byte (UAC2 standard).

### FU10 — Output Volume (wIndex=0x0A00) — CONFIRMED

| CS | Function | CH1 | CH2 | CH3 | CH4 |
|----|----------|-----|-----|-----|-----|
| 1 | Mute | 0xBB00 | 0xBB00 | 0xBB00 | 0xBB00 |
| 2 | Volume | 0x0000 (0 dB) | 0x0000 (0 dB) | 0x8080 (-127.5 dB) | 0x8080 (-127.5 dB) |

- Range: -127.00..0.00 dB (UAC2 16-bit signed, 1/256 dB steps)
- Only CH1-2 respond to SET_CUR. CH3-4 fixed at defaults.

### FU11 — Input Gain (wIndex=0x0B00) — CONFIRMED

| CS | Function | CH1 | CH2 | CH3 | CH4 |
|----|----------|-----|-----|-----|-----|
| 1 | Mute | 0x0080 | 0x0080 | 0x0080 | 0x0080 |
| 2 | Volume | varies | varies | 0x00F8 (-8 dB) | 0x00F8 (-8 dB) |

- Range: -8.00..+50.00 dB
- Only CH1-2 respond. CH3-4 fixed at -8 dB.

### EU50 (wIndex=0x3200) — NOT PRESENT

All GET_CUR and SET_CUR STALLed. No accessible controls.

### EU56 — Monitor Mix (wIndex=0x3800) — CONFIRMED

| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0 | 0x007F (127) | Monitor mix ratio: 0=input, 127=playback |
| 0 | 1-4 | 0x007F | Same value (global, not per-channel) |
| 1 | 0-4 | 0x0032 (50) | Unknown — writable, readback confirmed |
| 2-7 | 0-4 | 0x0000 | Zeros |

**WARNING:** Probing higher CS values can put EU56 into an error state
requiring USB re-plug. Only use CS=0 CN=0 for mix control.

### EU57 (wIndex=0x3900) — NOT PRESENT

All GET_CUR and SET_CUR STALLed. No accessible controls.

### EU58 — Input Config (wIndex=0x3A00) — FULLY MAPPED

| CS | CN | Value | Status | Notes |
|----|-----|-------|--------|-------|
| 0 | 0 | 0x00000000 | **CONFIRMED** | Phantom 48V input1: 0=off, 1=on |
| 0 | 1 | 0x00000000 | **CONFIRMED** | Phantom 48V input2: 0=off, 1=on |
| 0 | 2 | 0x00000000 | | Always 0 (no channel 3) |
| 1 | 0-2 | 0x00F8FFFF | read-only | Gain mirror (=FU11), first 2 bytes match FU11 CS=2 |
| 2 | 0 | 0x00000000 | **CONFIRMED** | Input mute ch1: 0=unmuted, 1=muted |
| 2 | 1 | 0x00000000 | **CONFIRMED** | Input mute ch2: 0=unmuted, 1=muted |
| 2 | 2 | 0x00000000 | | Always 0 |
| 3 | 0-2 | 0x00000000 | unused | |
| 4 | 0-2 | 0x00000000 | unused | |
| 5 | 0 | 0x00000000 | UNCONFIRMED | Writable, per-channel. Possibly input impedance/mode |
| 5 | 1 | 0xFFFFFFFF | UNCONFIRMED | (mic=0x00, instrument/line=0xFF?) |
| 5 | 2 | 0x00000000 | | Always 0 |
| 6 | 0-2 | 0x00000000 | unused | |
| 7 | 0 | 0x03000000 | read-only | Capability flags? (0x03 = bits 0+1 set) |
| 7 | 1 | 0x03000000 | read-only | Same for both channels |
| 7 | 2 | 0x00000000 | | |

**Phantom power:** SET_CUR with 4-byte LE payload. `\x01\x00\x00\x00` = ON,
`\x00\x00\x00\x00` = OFF. Per-channel (CN=0 for input1, CN=1 for input2).
Readback via GET_CUR confirmed. Relay click audible on toggle.

**CS=5 (unconfirmed):** Writable per-channel, SET/GET roundtrip works. Default
is CN=0=0, CN=1=0xFFFF. Accepts any 4-byte value. May control input
impedance/gain staging for XLR/TRS combo jacks, but no audible or visible
effect confirmed yet.

**CS=7 (read-only):** Value 0x03 for CN=0,1. Does not change when CS=5 is
toggled. Likely a static capability bitfield.

### EU59 — Output Config (wIndex=0x3B00) — FULLY MAPPED

| CS | CN | Value | Status | Notes |
|----|-----|-------|--------|-------|
| 0 | 0 | varies | read-only | Volume mirror (=FU10 CH1), 4-byte: `[vol_lo, vol_hi, 0xFF, 0xFF]` |
| 0 | 1 | varies | read-only | Volume mirror (=FU10 CH2) |
| 0 | 2-4 | 0x8080FFFF | read-only | Volume mirror (=FU10 CH3-4, -127.5 dB) |
| 1 | 0 | 0x00000000 | **CONFIRMED** | Output mute: 0=unmuted, 1=muted |
| 1 | 1 | 0x00000000 | | Tracks CN=0 (same mute state) |
| 1 | 2 | 0x00000000 | | Always 0 |
| 2 | 0 | 0x01000000 | UNCONFIRMED | Unknown boolean (val=1 for CN=0,1) |
| 2 | 1 | 0x01000000 | UNCONFIRMED | |
| 2 | 2 | 0x00000000 | | |

**EU59 CS=0 is NOT a separate headphone volume.** Tested by setting FU10 to
-20 dB and reading EU59 CS=0: first 2 bytes matched exactly (`00EC` = -20 dB).
vijay-prema's headphone volume writes to EU59 CS=0 but it's the same underlying
register as FU10. The `0xFFFF` padding in bytes 3-4 is the EU data format.

### MU60 — Mixer Unit (wIndex=0x3C00) — DECODED

Single 6-input × 2-output **loopback-only** mixer. All 12 cross-points
route into the loopback bus (USB capture CH3/4). This mixer does NOT control
headphone/main output — that is handled by EU56 (monitor mix) + FU10 (volume).

Write-only (all GET_CUR STALL). Uses CS=1 (Mixer Control, UAC2 standard),
2-byte signed Q8.8 dB values (1/256 dB steps). Range: -128 dB (0x8000,
silence) to +8 dB (0x0800).

Cross-point addressing follows UAC2: `CN = output_index + input_index * num_outputs`.

**Full matrix** (6 inputs × 2 outputs, CN 0-11):

| CN | Source          | Destination | input_idx | out_idx |
|----|-----------------|-------------|-----------|---------|
| 0  | Input 1         | Loopback L  | 0         | 0       |
| 1  | Input 1         | Loopback R  | 0         | 1       |
| 2  | Input 2         | Loopback L  | 1         | 0       |
| 3  | Input 2         | Loopback R  | 1         | 1       |
| 4  | DAW L (Main)    | Loopback L  | 2         | 0       |
| 5  | DAW L (Main)    | Loopback R  | 2         | 1       |
| 6  | DAW R (Main)    | Loopback L  | 3         | 0       |
| 7  | DAW R (Main)    | Loopback R  | 3         | 1       |
| 8  | LoopOut L (CH3) | Loopback L  | 4         | 0       |
| 9  | LoopOut L (CH3) | Loopback R  | 4         | 1       |
| 10 | LoopOut R (CH4) | Loopback L  | 5         | 0       |
| 11 | LoopOut R (CH4) | Loopback R  | 5         | 1       |

**Inputs 0-1** (Input 1/2): mic/line preamp signals after FU11 gain.
**Inputs 2-3** (DAW L/R): USB playback CH1/2 — the main stereo output.
**Inputs 4-5** (LoopOut L/R): USB playback CH3/4 — a second stereo playback
stream that only appears in the loopback mix (not in the headphone output).
On Linux, this requires a PipeWire loopback module to expose as a separate
sink (see `dev/linux-audio/evo4-stereo.conf`).

Default state (from USB captures): diagonal cross-points active (CN 0,3,4,7,8,11),
cross pairs muted at -128 dB (CN 1,2,5,6,9,10). Volume and pan sweeps change
proportional cross-point pairs as expected.

Cross-referenced with soerenbnoergaard/evoctl (EVO8): same protocol
(wIndex=0x3C00, CS=1, 2-byte Q8.8 dB), same write-only behavior, no pan law
in hardware. EVO8 uses a larger matrix (10×4=40 cross-points) but same
addressing formula.

## Protocol Summary

| Control | Entity | wValue | wIndex | Payload | Status |
|---------|--------|--------|--------|---------|--------|
| Output Volume | FU10 | CS=2, CN=1-2 | 0x0A00 | 2B signed (1/256 dB) | CONFIRMED |
| Input Gain | FU11 | CS=2, CN=1-2 | 0x0B00 | 2B signed (1/256 dB) | CONFIRMED |
| Monitor Mix | EU56 | CS=0, CN=0 | 0x3800 | 2B unsigned (0-127) | CONFIRMED |
| Input Mute | EU58 | CS=2, CN=0-1 | 0x3A00 | 4B LE boolean | CONFIRMED |
| Output Mute | EU59 | CS=1, CN=0 | 0x3B00 | 4B LE boolean | CONFIRMED |
| Phantom 48V | EU58 | CS=0, CN=0-1 | 0x3A00 | 4B LE boolean | CONFIRMED |
| Mixer Matrix | MU60 | CS=1, CN=0-11 | 0x3C00 | 2B signed (1/256 dB) | CONFIRMED (write-only) |
| Input Mode? | EU58 | CS=5, CN=0-1 | 0x3A00 | 4B LE | UNCONFIRMED |
| Volume (alias) | EU59 | CS=0, CN=0-1 | 0x3B00 | 4B (=FU10 mirror) | read-only mirror |

## Known Quirks

1. **EU56 error state** — Sending GET_CUR to invalid CS/CN on EU56 can lock
   the unit. Only recoverable by USB re-plug.

2. **Rapid transfer storms** — Opening/closing `/dev/evo4` many times in
   fast succession (e.g., scan with per-command open) can cause USB STALL
   on all subsequent transfers. Use a single fd with delays between transfers.

3. **CH3-4 are internal** — Both FU10 and FU11 report 4 channels in their USB
   descriptors, but CH3-4 are fixed at defaults and ignore SET_CUR. They
   appear to be internal routing channels.

4. **Mute/phantom data size** — EU58/59 controls use 4-byte values despite
   being boolean. Must send full 4 bytes or the device ignores the request.

5. **No front panel USB access** — The physical buttons (input1, input2,
   volume, mixer, 48V) and rotary encoder are handled by the device's
   internal microcontroller. Button state is not readable or writable via
   USB control transfers. There is no HID interface.

## Cross-Reference: Other Projects

| Control | Our Project | vijay-prema | Evo4mixer | evoctl (EVO8) | MixiD (iD) |
|---------|------------|-------------|-----------|---------------|-------------|
| Output Volume | FU10 CS=2 | EU59 CS=0 (alias) | EU59 CS=0 (alias) | - | EU54 |
| Input Gain | FU11 CS=2 | EU58 CS=1 (alias) | EU58 CS=1 (alias) | - | FU11 |
| Monitor Mix | EU56 CS=0 | - | MU60 | MU60 (matrix) | - |
| Input Mute | EU58 CS=2 | - | - | - | - |
| Output Mute | EU59 CS=1 | - | - | - | EU54 |
| Phantom 48V | EU58 CS=0 | EU58 CS=0 | EU58 CS=0 | - | - |
| HP Volume | N/A (=FU10) | EU59 CS=0 (=FU10) | - | - | FU10 CH3-4 |
| Mixer Matrix | MU60 CS=1 (decoded) | - | MU60 | MU60 (matrix) | EU60 routing |
