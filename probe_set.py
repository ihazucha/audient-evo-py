"""Test SET_CUR on EU56 to see if it controls monitor mix.

Run this while listening to audio — if the mix changes audibly, we found it.
"""

import evo4_kmod
import struct
import sys
import time

EU56 = 0x3800

def get_eu56(fd, cs, cn):
    data = evo4_kmod.get_cur(fd, wValue=(cs << 8) | cn, wIndex=EU56, length=2)
    return int.from_bytes(data[:2], "little", signed=True)

def set_eu56(fd, cs, cn, value):
    data = value.to_bytes(2, "little", signed=True)
    evo4_kmod.set_cur(fd, wValue=(cs << 8) | cn, wIndex=EU56, data=data)

def main():
    if len(sys.argv) < 2:
        print("Usage: python probe_set.py <value 0-254>")
        print("       python probe_set.py read")
        sys.exit(1)

    fd = evo4_kmod.open_device()

    if sys.argv[1] == "read":
        for cs in range(3):
            for cn in range(3):
                try:
                    v = get_eu56(fd, cs, cn)
                    print(f"  EU56 CS={cs} CN={cn}: {v} (0x{v & 0xFFFF:04X})")
                except OSError as e:
                    print(f"  EU56 CS={cs} CN={cn}: STALL ({e})")
        fd.close()
        return

    value = int(sys.argv[1])
    print(f"Current EU56 CS=0 CN=0: {get_eu56(fd, 0, 0)}")
    print(f"Setting EU56 CS=0 CN=0 to {value}...")

    try:
        set_eu56(fd, 0, 0, value)
        print(f"Success! Readback: {get_eu56(fd, 0, 0)}")
    except OSError as e:
        print(f"SET_CUR failed: {e}")
        print("Trying CS=1...")
        try:
            set_eu56(fd, 1, 0, value)
            print(f"CS=1 success! Readback: {get_eu56(fd, 1, 0)}")
        except OSError as e2:
            print(f"CS=1 also failed: {e2}")

    fd.close()

if __name__ == "__main__":
    main()
