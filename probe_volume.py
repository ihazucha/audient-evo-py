"""Probe and control FU10 (output volume) via kernel module.

Only touches known-safe CS values (1=mute, 2=volume) to avoid
putting the unit into an error state.

UAC2 Feature Unit volume is 16-bit signed, in 1/256 dB steps.
  0x0000 =   0.00 dB (max)
  0xFF00 =  -1.00 dB
  0x8080 = -127.5 dB (effectively muted)
  Range for EVO4 FU10: -12700..0 cB = -127.00..0.00 dB
"""

import evo4_kmod
import sys

FU10 = 0x0A00  # (EntityID=0x0A << 8) | Interface=0
FU11 = 0x0B00  # (EntityID=0x0B << 8) | Interface=0

CS_MUTE = 1
CS_VOLUME = 2

def db_to_raw(db: float) -> int:
    """Convert dB to UAC2 16-bit signed (1/256 dB steps)."""
    return int(db * 256) & 0xFFFF

def raw_to_db(raw: int) -> float:
    """Convert UAC2 16-bit signed to dB."""
    if raw > 0x7FFF:
        raw -= 0x10000
    return raw / 256.0

def get_volume(fd, unit, cn):
    data = evo4_kmod.get_cur(fd, wValue=(CS_VOLUME << 8) | cn, wIndex=unit, length=2)
    raw = int.from_bytes(data[:2], "little")
    return raw, raw_to_db(raw)

def get_mute(fd, unit, cn):
    data = evo4_kmod.get_cur(fd, wValue=(CS_MUTE << 8) | cn, wIndex=unit, length=2)
    raw = int.from_bytes(data[:2], "little")
    return raw

def set_volume(fd, unit, cn, db):
    raw = db_to_raw(db)
    data = raw.to_bytes(2, "little")
    evo4_kmod.set_cur(fd, wValue=(CS_VOLUME << 8) | cn, wIndex=unit, data=data)

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python probe_volume.py read [fu10|fu11]")
        print("  python probe_volume.py set <channel 1-4> <dB value> [fu10|fu11]")
        print("  python probe_volume.py set 1 -10.0    # ch1 to -10 dB")
        print("  python probe_volume.py set 1 0        # ch1 to 0 dB (max)")
        sys.exit(1)

    unit_name = sys.argv[-1] if sys.argv[-1] in ("fu10", "fu11") else "fu10"
    unit = FU10 if unit_name == "fu10" else FU11

    fd = evo4_kmod.open_device()

    if sys.argv[1] == "read":
        print(f"=== {unit_name.upper()} ({'Output Volume' if unit == FU10 else 'Input Gain'}) ===")
        for cn in range(1, 5):
            try:
                raw, db = get_volume(fd, unit, cn)
                mute_raw = get_mute(fd, unit, cn)
                mute = "MUTED" if mute_raw & 1 else "unmuted"
                print(f"  CH{cn}: {db:+.2f} dB (raw=0x{raw:04X})  mute={mute} (raw=0x{mute_raw:04X})")
            except OSError as e:
                print(f"  CH{cn}: error ({e})")

    elif sys.argv[1] == "set":
        cn = int(sys.argv[2])
        db = float(sys.argv[3])
        print(f"Setting {unit_name.upper()} CH{cn} to {db:+.2f} dB...")
        try:
            set_volume(fd, unit, cn, db)
            raw, readback = get_volume(fd, unit, cn)
            print(f"  Readback: {readback:+.2f} dB (raw=0x{raw:04X})")
        except OSError as e:
            print(f"  Failed: {e}")

    fd.close()

if __name__ == "__main__":
    main()
