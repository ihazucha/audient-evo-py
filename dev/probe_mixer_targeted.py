#!/usr/bin/env python3
"""Targeted MU60 probe — test specific CN ranges with clear labeling.

Tests two scenarios:
  A) Mic on Input2 only (no YouTube) — find which CNs carry mic signal
  B) YouTube on Main Output (CH1/2) — find which CNs carry DAW signal

Usage:
  python dev/probe_mixer_targeted.py
"""

import sys
sys.path.insert(0, ".")

from evo4 import kmod
from evo4.controller import _db_to_usb, _MU60, _CS_MIXER, _MIXER_DB_MIN

MUTE = _db_to_usb(_MIXER_DB_MIN)
UNITY = _db_to_usb(0.0)
MAX_CN = 32


def set_cn(fd, cn, raw):
    kmod.set_cur(fd, wValue=(_CS_MIXER << 8) | cn, wIndex=_MU60,
                 data=raw.to_bytes(2, "little"))


def mute_all(fd):
    for cn in range(MAX_CN):
        try:
            set_cn(fd, cn, MUTE)
        except OSError:
            pass


# Hypothesized layout (stride 2, 4 inputs, 2 output buses):
HYPOTHETICAL = {
    # Output bus (headphones)
    0: "Input1  → Out L",
    1: "Input1  → Out R",
    2: "Input2  → Out L",
    3: "Input2  → Out R",
    4: "DAW L   → Out L",
    5: "DAW L   → Out R",
    6: "DAW R   → Out L",
    7: "DAW R   → Out R",
    # Loopback bus
    8:  "Input1  → Loop L",
    9:  "Input1  → Loop R",
    10: "Input2  → Loop L",
    11: "Input2  → Loop R",
    12: "DAW L   → Loop L",
    13: "DAW L   → Loop R",
    14: "DAW R   → Loop L",
    15: "DAW R   → Loop R",
}


def main():
    print("MU60 Targeted Probe")
    print("=" * 60)
    print()
    print("Monitoring: OBS on EVO4 Loopback Capture")
    print("Also check: do you hear anything in headphones?")
    print()
    print("For each CN, report what you observe:")
    print("  L  = signal on LEFT meter only")
    print("  R  = signal on RIGHT meter only")
    print("  B  = signal on BOTH meters")
    print("  H  = heard in headphones (even if not on OBS)")
    print("  -  = nothing")
    print("  q  = quit")
    print()

    with kmod.open_device() as fd:
        mute_all(fd)

        print("─" * 60)
        print("PHASE 1: Mic on Input2, NO YouTube playing")
        print("         (or set YouTube to a sink that's not EVO4)")
        print("─" * 60)
        input("Press Enter when ready...")
        print()

        results_mic = {}
        for cn in range(MAX_CN):
            mute_all(fd)
            hyp = HYPOTHETICAL.get(cn, "???")
            try:
                set_cn(fd, cn, UNITY)
            except OSError:
                print(f"  CN {cn:2d}  [{hyp:20s}]  ERROR (rejected)")
                continue

            resp = input(f"  CN {cn:2d}  [{hyp:20s}]  signal? ").strip().lower()
            if resp == "q":
                break
            results_mic[cn] = resp

        mute_all(fd)
        print()
        print("─" * 60)
        print("PHASE 2: YouTube playing → EVO4 Main Output (CH1/2)")
        print("         Keep mic on Input2 as well")
        print("─" * 60)
        input("Press Enter when ready...")
        print()

        results_daw = {}
        for cn in range(MAX_CN):
            mute_all(fd)
            hyp = HYPOTHETICAL.get(cn, "???")
            try:
                set_cn(fd, cn, UNITY)
            except OSError:
                print(f"  CN {cn:2d}  [{hyp:20s}]  ERROR (rejected)")
                continue

            resp = input(f"  CN {cn:2d}  [{hyp:20s}]  signal? ").strip().lower()
            if resp == "q":
                break
            results_daw[cn] = resp

        mute_all(fd)

        # Summary
        print()
        print("=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)
        print(f"{'CN':>4s}  {'Hypothesis':20s}  {'Mic only':10s}  {'Mic+DAW':10s}")
        print("-" * 60)
        all_cns = sorted(set(results_mic.keys()) | set(results_daw.keys()))
        for cn in all_cns:
            hyp = HYPOTHETICAL.get(cn, "???")
            mic = results_mic.get(cn, "?")
            daw = results_daw.get(cn, "?")
            if mic != "-" or daw != "-":
                marker = " ◄◄◄" if (mic not in ("-", "?") or daw not in ("-", "?")) else ""
                print(f"  {cn:2d}    {hyp:20s}  {mic:10s}  {daw:10s}{marker}")


if __name__ == "__main__":
    main()
