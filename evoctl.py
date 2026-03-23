import argparse
import errno
import sys
from evo4.controller import EVO4Controller
from evo4.config import CONFIG_FILE

PARAMETERS = ["volume", "gain", "mute", "mix", "phantom"]
INPUT_TARGETS = ["input1", "input2"]
MUTE_TARGETS = ["input1", "input2", "output"]


def parse_args():
    parser = argparse.ArgumentParser(description="Audient EVO4 config tool.")
    sparser = parser.add_subparsers(dest="action", required=True)

    get_p = sparser.add_parser("get", aliases=["g"], help="Get device param.")
    get_p.add_argument("parameter", choices=PARAMETERS)
    get_p.add_argument("--target", "-t", choices=MUTE_TARGETS, default=None)
    get_p.add_argument("--db", action="store_true", help="Get as dB.")

    set_p = sparser.add_parser("set", aliases=["s"], help="Set device param.")
    set_p.add_argument("parameter", choices=PARAMETERS)
    set_p.add_argument("value", type=str)
    set_p.add_argument("--target", "-t", choices=MUTE_TARGETS, default=None)
    set_p.add_argument("--db", action="store_true", help="Set as dB.")

    status_p = sparser.add_parser("status", help="Show all device params.")
    status_p.add_argument("--format", "-f", choices=["plain", "json"], default="plain")

    save_p = sparser.add_parser("save", help="Save config to file.")
    save_p.add_argument("path", nargs="?", default=None, help=f"Defa: {CONFIG_FILE}.")
    load_p = sparser.add_parser("load", help="Load and apply config from file.")
    load_p.add_argument("path", nargs="?", default=None, help=f"Defa: {CONFIG_FILE}.")

    # Mixer
    mixer_p = sparser.add_parser("mixer", aliases=["m"], help="Loopback mixer config.")
    mixer_sp = mixer_p.add_subparsers(dest="mixer_section", required=True)

    _VOLUME_HELP = "dB (mute) <-128,6> (gain). 0 == pass as is."
    for inp in ("input1", "input2"):
        inp_p = mixer_sp.add_parser(inp, help=f"Set {inp} level in loopback mix.")
        inp_p.add_argument("--volume", type=float, required=True, help=_VOLUME_HELP)
        inp_p.add_argument(
            "--pan",
            type=float,
            default=0.0,
            help="(left) <-100,100> (right). Default: 0 (center).",
        )

    for out in ("output", "loopback"):
        out_p = mixer_sp.add_parser(out, help=f"Set {out} level in loopback mix.")
        out_p.add_argument("--volume", type=float, required=True, help=_VOLUME_HELP)
        out_p.add_argument(
            "--pan-l",
            type=float,
            default=-100.0,
            help="L channel (left) <-100,100> (right). Default: -100.",
        )
        out_p.add_argument(
            "--pan-r",
            type=float,
            default=100.0,
            help="R channel (left) <-100,100> (right). Default: 100.",
        )

    args = parser.parse_args()

    if args.action in ("status", "save", "load", "mixer", "m"):
        return args

    if args.action in ("set", "s"):
        if args.parameter in ("volume", "gain", "mix"):
            if args.db and args.parameter in ("volume", "gain"):
                try:
                    args.value = float(args.value)
                except ValueError:
                    parser.error(f"{args.parameter} dB value must be a number.")
                if args.parameter == "volume" and not (-96.0 <= args.value <= 0.0):
                    parser.error("Volume must be between -96 and 0 dB.")
                if args.parameter == "gain" and not (-8.0 <= args.value <= 50.0):
                    parser.error("Gain must be between -8 and 50 dB.")
            else:
                try:
                    args.value = int(args.value)
                except ValueError:
                    parser.error(f"{args.parameter} value must be an integer.")
                if not (0 <= args.value <= 100):
                    parser.error(f"{args.parameter.capitalize()} must be between 0 and 100.")
        else:
            if args.parameter in ["mute", "phantom"]:
                if args.value not in ("1", "0"):
                    parser.error(f"{args.parameter} value must be 1/0.")
                args.value = args.value == "1"

    for p, ts in [
        ("gain", INPUT_TARGETS),
        ("mute", MUTE_TARGETS),
        ("phantom", INPUT_TARGETS),
    ]:
        if args.parameter == p:
            if not args.target or args.target not in ts:
                parser.error(f"{p} requires --target/-t <{'|'.join(INPUT_TARGETS)}>.")

    return args


def _format_status_plain(state: dict) -> str:
    W = 10  # label column width ("phantom:" = 8 chars, padded to 10)
    lines = []
    for ch, label in (("input1", "Input 1"), ("input2", "Input 2")):
        inp = state[ch]
        gain_db = EVO4Controller._gain_pct_to_db(inp["gain"])
        lines.append(f"{label}:")
        lines.append(f"  {'gain:':<{W}}{inp['gain']:>3d}%  ({gain_db:+.2f} dB)")
        lines.append(f"  {'mute:':<{W}}{'on' if inp['mute'] else 'off'}")
        lines.append(f"  {'phantom:':<{W}}{'on' if inp['phantom'] else 'off'}")
        lines.append("")
    out = state["output"]
    vol_db = EVO4Controller._vol_pct_to_db(out["volume"])
    lines.append("Main output 1|2:")
    lines.append(f"  {'volume:':<{W}}{out['volume']:>3d}%  ({vol_db:+.2f} dB)")
    lines.append(f"  {'mute:':<{W}}{'on' if out['mute'] else 'off'}")
    lines.append("")
    lines.append(f"Monitor mix: {state['monitor']}%")
    return "\n".join(lines)


def _run(args, evo: EVO4Controller):
    if args.action in ("get", "g"):
        if args.parameter == "volume":
            pct, raw, db = evo.get_volume_debug()
            print(f"[GET] Volume: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == "gain":
            pct, raw, db = evo.get_gain_debug(args.target)
            print(f"[GET] Gain {args.target}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == "mute":
            muted = evo.get_mute(args.target)
            print(f"[GET] Mute {args.target}: {'on' if muted else 'off'}")

        elif args.parameter == "mix":
            mix = evo.get_mix()
            print(f"[GET] Mix: {mix}% (0=input, 100=playback)")

        elif args.parameter == "phantom":
            state = evo.get_phantom(args.target)
            print(f"[GET] Phantom 48V {args.target}: {'on' if state else 'off'}")

    elif args.action in ("set", "s"):
        if args.parameter == "volume":
            raw, db = evo.set_volume_db(args.value) if args.db else evo.set_volume(args.value)
            print(f"[SET] Volume: {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == "gain":
            raw, db = (
                evo.set_gain_db(args.target, args.value)
                if args.db
                else evo.set_gain(args.target, args.value)
            )
            print(f"[SET] Gain {args.target}: {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == "mute":
            evo.set_mute(args.target, args.value)
            print(f"[SET] Mute {args.target}: {'1' if args.value else '0'}")

        elif args.parameter == "mix":
            evo.set_mix(args.value)
            print(f"[SET] Mix: {args.value}% (0=input, 100=playback)")

        elif args.parameter == "phantom":
            evo.set_phantom(args.target, args.value)
            print(f"[SET] Phantom 48V {args.target}: {'on' if args.value else 'off'}")

    elif args.action in ("mixer", "m"):
        from evo4.config import load_mixer_state, save_mixer_state

        sec = args.mixer_section
        state = load_mixer_state() or {}
        if sec in ("input1", "input2"):
            num = int(sec[-1])
            evo.set_mixer_input(num, args.volume, args.pan)
            state[sec] = {"volume": args.volume, "pan": args.pan}
            print(f"[SET] Mixer {sec}: volume={args.volume:+.1f} dB, pan={args.pan:+.0f}")
        elif sec == "output":
            evo.set_mixer_output(args.volume, args.pan_l, args.pan_r)
            state["output"] = {
                "volume": args.volume,
                "pan_l": args.pan_l,
                "pan_r": args.pan_r,
            }
            print(
                f"[SET] Mixer output: volume={args.volume:+.1f} dB, "
                f"pan_l={args.pan_l:+.0f}, pan_r={args.pan_r:+.0f}"
            )
        elif sec == "loopback":
            evo.set_mixer_loopback(args.volume, args.pan_l, args.pan_r)
            state["loopback"] = {
                "volume": args.volume,
                "pan_l": args.pan_l,
                "pan_r": args.pan_r,
            }
            print(
                f"[SET] Mixer loopback: volume={args.volume:+.1f} dB, "
                f"pan_l={args.pan_l:+.0f}, pan_r={args.pan_r:+.0f}"
            )
        save_mixer_state(state)

    elif args.action == "save":
        from evo4.config import save

        path = save(evo, args.path)
        print(f"Config saved to {path}")

    elif args.action == "load":
        from evo4.config import load_and_apply

        load_and_apply(evo, args.path)
        print("Config loaded and applied.")

    elif args.action == "status":
        state = EVO4Controller.decode_status(evo.get_status_raw())
        if args.format == "json":
            import json

            print(json.dumps(state, indent=2))
        else:
            print(_format_status_plain(state))


_USB_ERRORS = {
    errno.ENODEV: "EVO4 not connected (or USB device was removed).",
    errno.EPIPE: "USB STALL: device rejected the command.",
    errno.EPROTO: "USB protocol error — try unplugging and replugging the device.",
    errno.ETIMEDOUT: "USB timeout — try unplugging and replugging the device.",
}

if __name__ == "__main__":
    args = parse_args()
    try:
        evo = EVO4Controller()
        _run(args, evo)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        msg = _USB_ERRORS.get(e.errno if e.errno else -1, f"USB error: {e}")
        print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)
