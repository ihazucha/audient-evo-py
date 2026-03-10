"""Probe Mixer Unit 60 and Extension Units to discover valid control selectors.

Sends GET_CUR requests with various wValue/wIndex combinations and reports
which ones the device responds to (vs STALLing).
"""

import evo4_kmod
import struct

# Entity IDs from USB descriptors, wIndex = (EntityID << 8) | Interface(0)
UNITS = {
    "FU10 (output vol)":  0x0A00,
    "FU11 (input gain)":  0x0B00,
    "EU50":               0x3200,
    "EU56":               0x3800,
    "EU57":               0x3900,
    "EU58":               0x3A00,
    "EU59 (mute)":        0x3B00,
    "MU60 (mixer)":       0x3C00,
}

def probe():
    fd = evo4_kmod.open_device()

    for name, wIndex in UNITS.items():
        print(f"\n=== {name} (wIndex=0x{wIndex:04X}) ===")
        for cs in range(0, 8):       # control selector 0-7
            for cn in range(0, 5):   # channel number 0-4
                wValue = (cs << 8) | cn
                try:
                    # Try different lengths — some controls return 1, 2, or 4 bytes
                    for length in (2, 4, 1):
                        try:
                            data = evo4_kmod.get_cur(fd, wValue=wValue, wIndex=wIndex, length=length)
                            hex_data = data.hex() if data else "(empty)"
                            print(f"  CS={cs} CN={cn} len={length}: {hex_data}")
                            break
                        except OSError:
                            continue
                except OSError:
                    pass  # STALL — not a valid combination

    fd.close()

if __name__ == "__main__":
    probe()
