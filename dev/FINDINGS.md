# Reverse Engineering Findings

Raw probe results from scanning the Audient EVO4's USB entities.
Gathered using `probe.py scan` and targeted GET/SET experiments.

## Methodology

1. Enumerated USB descriptors to identify entities (Feature Units, Extension
   Units, Mixer Unit) and their IDs
2. Sent GET_CUR with every CS (0-7) x CN (0-4) combination on each entity
3. For entities that responded: varied values with SET_CUR and observed effects
4. Matched behavior to vendor app controls (volume, gain, mute, monitor mix)

## Probe Results

wIndex = `(EntityID << 8) | Interface(0)`, wValue = `(CS << 8) | CN`.
All values 2-byte little-endian unless noted.

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

### EU50 (wIndex=0x3200) — All STALLs

No valid controls found.

### EU56 — Monitor Mix (wIndex=0x3800) — CONFIRMED

| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0 | 0x007F (127) | Monitor mix ratio: 0=input, 127=playback |
| 0 | 1-4 | 0x007F | Same value (global, not per-channel) |
| 1 | 0-4 | 0x0032 (50) | Unknown secondary parameter |
| 2-7 | 0-4 | 0x0000 | Zeros |

**WARNING:** Probing higher CS values can put EU56 into an error state
requiring USB re-plug. Only use CS=0 CN=0 for mix control.

### EU57 (wIndex=0x3900) — All STALLs

No valid controls found.

### EU58 — Input Config (wIndex=0x3A00) — PARTIALLY MAPPED

| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0-4 | 0x0000 | Unknown |
| 1 | 0 | 0x00F8 (-8 dB?) | Mirrors FU11 gain default? |
| 1 | 1 | 0x0032 (50) | Mirrors FU11 gain ch2? |
| 1 | 2-4 | 0x00F8 | Same as CN=0 |
| 2-4 | 0-4 | 0x0000 | Zeros |
| 5 | 1 | 0xFFFF | Flag/boolean? |
| 5 | 0,2-4 | 0x0000 | |
| 6 | 0-4 | 0x0000 | Zeros |
| 7 | 0-1 | 0x0003 | Unknown config |
| 7 | 2-4 | 0x0000 | |

Likely candidates for unmapped controls: input select, phantom power.
Needs further SET_CUR experiments.

Input mute confirmed at CS=2: CN=0 for input 1, CN=1 for input 2.
Data: 4 bytes LE, 0x01=muted, 0x00=unmuted.

### EU59 — Output Mute (wIndex=0x3B00) — CONFIRMED

| CS | CN | Value | Notes |
|----|----|-------|-------|
| 0 | 0-1 | 0x0000 | Unknown |
| 0 | 2-4 | 0x8080 | Mirrors FU10 ch3-4 mute? |
| 1 | 0-4 | 0x0000 | Mute control (4 bytes LE, 0x01=muted) |
| 2 | 0-1 | 0x0100 | Unknown |
| 2 | 2-4 | 0x0000 | |

### MU60 — Mixer Unit (wIndex=0x3C00) — All STALLs

Firmware does not implement standard UAC2 mixer controls.
Actual mixing is controlled via EU56.

## Known Quirks

1. **EU56 error state** — Sending GET_CUR to invalid CS/CN on EU56 can lock
   the unit. Only recoverable by USB re-plug.

2. **CH3-4 are internal** — Both FU10 and FU11 report 4 channels in their USB
   descriptors, but CH3-4 are fixed at defaults and ignore SET_CUR. They
   appear to be internal routing channels.

3. **Mute data size** — EU58/59 mute controls use 4-byte values despite being
   boolean. Must send full 4 bytes or the device ignores the request.
