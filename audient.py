import argparse
import sys

if sys.platform == "linux":
    from evo4_alsa import EVO4Controller
elif sys.platform == "win32":
    from evo4_usb import EVO4Controller
else:
    sys.exit(f"Unsupported platform: {sys.platform}")


PARAMETERS = ['volume', 'gain', 'mute', 'mix']

def parse_args():
    parser = argparse.ArgumentParser(description="Control Audient EVO4 settings.")
    subparsers = parser.add_subparsers(dest='action', required=True)

    get_parser = subparsers.add_parser('get', aliases=['g'], help='Get a device parameter.')
    get_parser.add_argument('parameter', choices=PARAMETERS)
    get_parser.add_argument('--channel', '-c', type=int, default=None,
                            help='Channel number (1-based). Omit for all channels.')

    set_parser = subparsers.add_parser('set', aliases=['s'], help='Set a device parameter.')
    set_parser.add_argument('parameter', choices=PARAMETERS)
    set_parser.add_argument('value', type=str)
    set_parser.add_argument('--channel', '-c', type=int, default=None,
                            help='Channel number (1-based). Omit for all channels.')

    args = parser.parse_args()

    if args.action in ('set', 's'):
        if args.parameter in ('volume', 'gain', 'mix'):
            try:
                args.value = int(args.value)
            except ValueError:
                parser.error(f"{args.parameter} value must be an integer.")
            if args.parameter == 'volume' and not (0 <= args.value <= 100):
                parser.error("Volume must be between 0 and 100.")
            if args.parameter == 'gain' and not (0 <= args.value <= 100):
                parser.error("Gain must be between 0 and 100.")
            if args.parameter == 'mix' and not (0 <= args.value <= 100):
                parser.error("Mix must be between 0 and 100 (0=input, 100=playback).")
        elif args.parameter == 'mute':
            if args.value.lower() in ('1', 'true', 'on'):
                args.value = True
            elif args.value.lower() in ('0', 'false', 'off'):
                args.value = False
            else:
                parser.error("Mute value must be on/off, true/false, or 1/0.")

    return args


if __name__ == "__main__":
    args = parse_args()
    evo = EVO4Controller()

    if args.action in ('get', 'g'):
        if args.parameter == 'volume':
            volumes = evo.get_volume()
            if args.channel is not None:
                print(f"[GET] Volume ch{args.channel}: {volumes[args.channel - 1]}%")
            else:
                for i, v in enumerate(volumes, 1):
                    print(f"[GET] Volume ch{i}: {v}%")

        elif args.parameter == 'gain':
            gains = evo.get_gain()
            if args.channel is not None:
                print(f"[GET] Gain ch{args.channel}: {gains[args.channel - 1]}%")
            else:
                for i, v in enumerate(gains, 1):
                    print(f"[GET] Gain ch{i}: {v}%")

        elif args.parameter == 'mute':
            muted = evo.get_mute()
            print(f"[GET] Mute: {'on' if muted else 'off'}")

        elif args.parameter == 'mix':
            mix = evo.get_mix()
            print(f"[GET] Mix: {mix}% (0=input, 100=playback)")

    elif args.action in ('set', 's'):
        if args.parameter == 'volume':
            evo.set_volume(args.value, channel=args.channel)
            print(f"[SET] Volume: {args.value}%"
                  + (f" ch{args.channel}" if args.channel else ""))

        elif args.parameter == 'gain':
            evo.set_gain(args.value, channel=args.channel)
            print(f"[SET] Gain: {args.value}%"
                  + (f" ch{args.channel}" if args.channel else ""))

        elif args.parameter == 'mute':
            evo.set_mute(args.value)
            print(f"[SET] Mute: {'on' if args.value else 'off'}")

        elif args.parameter == 'mix':
            evo.set_mix(args.value)
            print(f"[SET] Mix: {args.value}% (0=input, 100=playback)")
