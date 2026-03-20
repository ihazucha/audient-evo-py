import argparse
import errno
import sys
from evo4.controller import EVO4Controller

PARAMETERS = ['volume', 'gain', 'mute', 'mix', 'phantom']

def parse_args():
    parser = argparse.ArgumentParser(description="Control Audient EVO4 settings.")
    subparsers = parser.add_subparsers(dest='action', required=True)

    MUTE_TARGETS = ['input1', 'input2', 'output']
    PHANTOM_TARGETS = ['input1', 'input2']

    get_parser = subparsers.add_parser('get', aliases=['g'], help='Get a device parameter.')
    get_parser.add_argument('parameter', choices=PARAMETERS)
    get_parser.add_argument('--channel', '-c', type=int, default=None,
                            help='Channel number (1-based). Omit for all channels.')
    get_parser.add_argument('--target', '-t', choices=MUTE_TARGETS, default=None,
                            help='Mute target (input1, input2, output).')
    get_parser.add_argument('--db', action='store_true',
                            help='Show volume/gain in dB only (no percentage).')

    set_parser = subparsers.add_parser('set', aliases=['s'], help='Set a device parameter.')
    set_parser.add_argument('parameter', choices=PARAMETERS)
    set_parser.add_argument('value', type=str)
    set_parser.add_argument('--channel', '-c', type=int, default=None,
                            help='Channel number (1-based). Omit for all channels.')
    set_parser.add_argument('--target', '-t', choices=MUTE_TARGETS, default=None,
                            help='Mute target (input1, input2, output).')
    set_parser.add_argument('--db', action='store_true',
                            help='Interpret value as dB instead of percentage.')

    subparsers.add_parser('status', help='Show all device parameters.')

    save_parser = subparsers.add_parser('save', help='Save device config to file.')
    save_parser.add_argument('path', nargs='?', default=None,
                             help='Config file path (default: ~/.config/audient-evo-py/config.json).')

    load_parser = subparsers.add_parser('load', help='Load and apply config from file.')
    load_parser.add_argument('path', nargs='?', default=None,
                             help='Config file path (default: ~/.config/audient-evo-py/config.json).')

    # --- mixer subcommand ---
    mixer_parser = subparsers.add_parser('mixer', aliases=['m'],
                                         help='Control MU60 mixer matrix.')
    mixer_sub = mixer_parser.add_subparsers(dest='mixer_section', required=True)

    # mixer input1 / input2
    for inp in ('input1', 'input2'):
        inp_p = mixer_sub.add_parser(inp, help=f'Set {inp} level in output mix.')
        inp_p.add_argument('--volume', type=float, required=True,
                           help='Volume in dB (-128..+8). Use -128 to mute.')
        inp_p.add_argument('--pan', type=float, default=0.0,
                           help='Pan: -100 (left) to +100 (right). Default: 0 (center).')

    # mixer output
    out_p = mixer_sub.add_parser('output', help='Set DAW playback level in main output mix.')
    out_p.add_argument('--volume', type=float, required=True,
                       help='Volume in dB (-128..+8). Use -128 to mute.')
    out_p.add_argument('--pan-l', type=float, default=-100.0,
                       help='Pan for DAW L channel (-100..+100). Default: -100 (left).')
    out_p.add_argument('--pan-r', type=float, default=100.0,
                       help='Pan for DAW R channel (-100..+100). Default: +100 (right).')

    # mixer loopback
    loop_p = mixer_sub.add_parser('loopback', help='Set DAW playback level in loopback capture mix.')
    loop_p.add_argument('--volume', type=float, required=True,
                        help='Volume in dB (-128..+8). Use -128 to mute.')
    loop_p.add_argument('--pan-l', type=float, default=-100.0,
                        help='Pan for DAW L channel (-100..+100). Default: -100 (left).')
    loop_p.add_argument('--pan-r', type=float, default=100.0,
                        help='Pan for DAW R channel (-100..+100). Default: +100 (right).')

    args = parser.parse_args()

    if args.action in ('status', 'save', 'load', 'mixer', 'm'):
        return args

    if args.action in ('set', 's'):
        if args.parameter in ('volume', 'gain', 'mix'):
            if args.db and args.parameter in ('volume', 'gain'):
                try:
                    args.value = float(args.value)
                except ValueError:
                    parser.error(f"{args.parameter} dB value must be a number.")
                if args.parameter == 'volume' and not (-96.0 <= args.value <= 0.0):
                    parser.error("Volume must be between -96 and 0 dB.")
                if args.parameter == 'gain' and not (-8.0 <= args.value <= 50.0):
                    parser.error("Gain must be between -8 and +50 dB.")
            else:
                try:
                    args.value = int(args.value)
                except ValueError:
                    parser.error(f"{args.parameter} value must be an integer.")
                if not (0 <= args.value <= 100):
                    parser.error(f"{args.parameter.capitalize()} must be between 0 and 100.")
        elif args.parameter == 'mute':
            if args.value.lower() in ('1', 'true', 'on'):
                args.value = True
            elif args.value.lower() in ('0', 'false', 'off'):
                args.value = False
            else:
                parser.error("Mute value must be on/off, true/false, or 1/0.")
        elif args.parameter == 'phantom':
            if args.value.lower() in ('1', 'true', 'on'):
                args.value = True
            elif args.value.lower() in ('0', 'false', 'off'):
                args.value = False
            else:
                parser.error("Phantom value must be on/off, true/false, or 1/0.")

    if args.parameter == 'mute' and not args.target:
        parser.error("Mute requires --target/-t (input1, input2, or output).")
    if args.parameter == 'phantom':
        if not args.target:
            parser.error("Phantom requires --target/-t (input1 or input2).")
        if args.target not in PHANTOM_TARGETS:
            parser.error("Phantom target must be input1 or input2.")

    return args


_USB_ERRORS = {
    errno.ENODEV: "EVO4 not connected (or USB device was removed).",
    errno.EPIPE: "USB STALL: device rejected the command.",
    errno.EPROTO: "USB protocol error — try unplugging and replugging the device.",
    errno.ETIMEDOUT: "USB timeout — try unplugging and replugging the device.",
}


def _run(args, evo):
    if args.action in ('get', 'g'):
        if args.parameter == 'volume':
            debug = evo.get_volume_debug()
            if args.channel is not None:
                pct, raw, db = debug[args.channel - 1]
                if args.db:
                    print(f"{db:+.2f}")
                else:
                    print(f"[GET] Volume ch{args.channel}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")
            else:
                for i, (pct, raw, db) in enumerate(debug, 1):
                    if args.db:
                        print(f"ch{i}: {db:+.2f} dB")
                    else:
                        print(f"[GET] Volume ch{i}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == 'gain':
            debug = evo.get_gain_debug()
            if args.channel is not None:
                pct, raw, db = debug[args.channel - 1]
                if args.db:
                    print(f"{db:+.2f}")
                else:
                    print(f"[GET] Gain ch{args.channel}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")
            else:
                for i, (pct, raw, db) in enumerate(debug, 1):
                    if args.db:
                        print(f"ch{i}: {db:+.2f} dB")
                    else:
                        print(f"[GET] Gain ch{i}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == 'mute':
            muted = evo.get_mute(args.target)
            print(f"[GET] Mute {args.target}: {'on' if muted else 'off'}")

        elif args.parameter == 'mix':
            mix = evo.get_mix()
            print(f"[GET] Mix: {mix}% (0=input, 100=playback)")

        elif args.parameter == 'phantom':
            state = evo.get_phantom(args.target)
            print(f"[GET] Phantom 48V {args.target}: {'on' if state else 'off'}")

    elif args.action in ('set', 's'):
        if args.parameter == 'volume':
            if args.db:
                raw, db = evo.set_volume_db(args.value, channel=args.channel)
            else:
                raw, db = evo.set_volume(args.value, channel=args.channel)
            ch_str = f" ch{args.channel}" if args.channel else ""
            print(f"[SET] Volume:{ch_str} {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == 'gain':
            if args.db:
                raw, db = evo.set_gain_db(args.value, channel=args.channel)
            else:
                raw, db = evo.set_gain(args.value, channel=args.channel)
            ch_str = f" ch{args.channel}" if args.channel else ""
            print(f"[SET] Gain:{ch_str} {db:+.2f} dB  (raw=0x{raw & 0xFFFF:04X})")

        elif args.parameter == 'mute':
            evo.set_mute(args.target, args.value)
            print(f"[SET] Mute {args.target}: {'on' if args.value else 'off'}")

        elif args.parameter == 'mix':
            evo.set_mix(args.value)
            print(f"[SET] Mix: {args.value}% (0=input, 100=playback)")

        elif args.parameter == 'phantom':
            if args.value:
                print(f"WARNING: 48V phantom power will be applied to {args.target}.")
            evo.set_phantom(args.target, args.value)
            print(f"[SET] Phantom 48V {args.target}: {'on' if args.value else 'off'}")

    elif args.action in ('mixer', 'm'):
        from evo4.config import load_mixer_state, save_mixer_state
        sec = args.mixer_section
        state = load_mixer_state() or {}
        if sec in ('input1', 'input2'):
            num = int(sec[-1])
            evo.set_mixer_input(num, args.volume, args.pan)
            state[sec] = {"volume": args.volume, "pan": args.pan}
            print(f"[SET] Mixer {sec}: volume={args.volume:+.1f} dB, pan={args.pan:+.0f}")
        elif sec == 'output':
            evo.set_mixer_output(args.volume, args.pan_l, args.pan_r)
            state["output"] = {"volume": args.volume, "pan_l": args.pan_l, "pan_r": args.pan_r}
            print(f"[SET] Mixer output: volume={args.volume:+.1f} dB, "
                  f"pan_l={args.pan_l:+.0f}, pan_r={args.pan_r:+.0f}")
        elif sec == 'loopback':
            evo.set_mixer_loopback(args.volume, args.pan_l, args.pan_r)
            state["loopback"] = {"volume": args.volume, "pan_l": args.pan_l, "pan_r": args.pan_r}
            print(f"[SET] Mixer loopback: volume={args.volume:+.1f} dB, "
                  f"pan_l={args.pan_l:+.0f}, pan_r={args.pan_r:+.0f}")
        save_mixer_state(state)

    elif args.action == 'save':
        from evo4.config import save
        path = save(evo, args.path)
        print(f"Config saved to {path}")

    elif args.action == 'load':
        from evo4.config import load_and_apply
        load_and_apply(evo, args.path)
        print("Config loaded and applied.")

    elif args.action == 'status':
        with evo:
            vol = evo.get_volume_debug()
            gain = evo.get_gain_debug()
            mix = evo.get_mix()
            phantom = {t: evo.get_phantom(t) for t in ['input1', 'input2']}
            mutes = {t: evo.get_mute(t) for t in ['input1', 'input2', 'output']}

        for i, (pct, raw, db) in enumerate(vol, 1):
            print(f"Volume ch{i}:  {pct:>3d}%  ({db:+.2f} dB)")
        for i, (pct, raw, db) in enumerate(gain, 1):
            print(f"Gain ch{i}:    {pct:>3d}%  ({db:+.2f} dB)")
        print(f"Monitor Mix:  {mix:>3d}%  (0=input, 100=playback)")
        print(f"Mute:         input1={'on' if mutes['input1'] else 'off'}  "
              f"input2={'on' if mutes['input2'] else 'off'}  "
              f"output={'on' if mutes['output'] else 'off'}")
        print(f"Phantom 48V:  input1={'on' if phantom['input1'] else 'off'}  "
              f"input2={'on' if phantom['input2'] else 'off'}")


if __name__ == "__main__":
    args = parse_args()
    try:
        evo = EVO4Controller()
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        _run(args, evo)
    except OSError as e:
        msg = _USB_ERRORS.get(e.errno, f"USB error: {e}")
        print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)
