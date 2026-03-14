import argparse
from evo4.controller import EVO4Controller

PARAMETERS = ['volume', 'gain', 'mute', 'mix']

def parse_args():
    parser = argparse.ArgumentParser(description="Control Audient EVO4 settings.")
    subparsers = parser.add_subparsers(dest='action', required=True)

    MUTE_TARGETS = ['input1', 'input2', 'output']

    get_parser = subparsers.add_parser('get', aliases=['g'], help='Get a device parameter.')
    get_parser.add_argument('parameter', choices=PARAMETERS)
    get_parser.add_argument('--channel', '-c', type=int, default=None,
                            help='Channel number (1-based). Omit for all channels.')
    get_parser.add_argument('--target', '-t', choices=MUTE_TARGETS, default=None,
                            help='Mute target (input1, input2, output).')

    set_parser = subparsers.add_parser('set', aliases=['s'], help='Set a device parameter.')
    set_parser.add_argument('parameter', choices=PARAMETERS)
    set_parser.add_argument('value', type=str)
    set_parser.add_argument('--channel', '-c', type=int, default=None,
                            help='Channel number (1-based). Omit for all channels.')
    set_parser.add_argument('--target', '-t', choices=MUTE_TARGETS, default=None,
                            help='Mute target (input1, input2, output).')

    args = parser.parse_args()

    if args.action in ('set', 's'):
        if args.parameter in ('volume', 'gain', 'mix'):
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

    if args.parameter == 'mute' and not args.target:
        parser.error("Mute requires --target/-t (input1, input2, or output).")

    return args


if __name__ == "__main__":
    args = parse_args()
    evo = EVO4Controller()

    if args.action in ('get', 'g'):
        if args.parameter == 'volume':
            debug = evo.get_volume_debug()
            if args.channel is not None:
                pct, raw, db = debug[args.channel - 1]
                print(f"[GET] Volume ch{args.channel}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")
            else:
                for i, (pct, raw, db) in enumerate(debug, 1):
                    print(f"[GET] Volume ch{i}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == 'gain':
            debug = evo.get_gain_debug()
            if args.channel is not None:
                pct, raw, db = debug[args.channel - 1]
                print(f"[GET] Gain ch{args.channel}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")
            else:
                for i, (pct, raw, db) in enumerate(debug, 1):
                    print(f"[GET] Gain ch{i}: {pct}%  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == 'mute':
            muted = evo.get_mute(args.target)
            print(f"[GET] Mute {args.target}: {'on' if muted else 'off'}")

        elif args.parameter == 'mix':
            mix = evo.get_mix()
            print(f"[GET] Mix: {mix}% (0=input, 100=playback)")

    elif args.action in ('set', 's'):
        if args.parameter == 'volume':
            raw, db = evo.set_volume(args.value, channel=args.channel)
            ch_str = f" ch{args.channel}" if args.channel else ""
            print(f"[SET] Volume: {args.value}%{ch_str}  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == 'gain':
            raw, db = evo.set_gain(args.value, channel=args.channel)
            ch_str = f" ch{args.channel}" if args.channel else ""
            print(f"[SET] Gain: {args.value}%{ch_str}  (raw=0x{raw & 0xFFFF:04X}, {db:+.2f} dB)")

        elif args.parameter == 'mute':
            evo.set_mute(args.target, args.value)
            print(f"[SET] Mute {args.target}: {'on' if args.value else 'off'}")

        elif args.parameter == 'mix':
            evo.set_mix(args.value)
            print(f"[SET] Mix: {args.value}% (0=input, 100=playback)")
