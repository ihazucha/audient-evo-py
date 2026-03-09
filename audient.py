import argparse
import ctypes
import os
import re
import sys
import math

AUDIENT_VENDOR_ID = 0x2708
EVO4_ID = 0x0006


# ── Volume conversion helpers ─────────────────────────────────────────────────

def volume_percent_to_dB(volume: int) -> float:
    """Map volume 0-100 to dB -96.0-0.0 with a power curve anchored at 50 -> -20 dB."""
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return -96.0 * (1.0 - (volume / 100.0) ** n)

def dB_to_volume_percent(db: float) -> int:
    """Inverse of volume_percent_to_dB: map dB -96.0-0.0 to volume 0-100."""
    db = max(-96.0, min(0.0, db))
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return round(100.0 * (1.0 + db / 96.0) ** (1.0 / n))


# ── Platform-specific device control ─────────────────────────────────────────

if sys.platform == 'linux':
    # Use ALSA (libasound) to read/write controls owned by snd-usb-audio.
    # No USB interface claiming needed — the kernel driver handles the USB side.

    _lib = ctypes.CDLL('libasound.so.2')
    _lib.snd_ctl_open.restype               = ctypes.c_int
    _lib.snd_ctl_elem_list_get_name.restype  = ctypes.c_char_p
    _lib.snd_ctl_elem_list_get_numid.restype = ctypes.c_uint
    _lib.snd_ctl_elem_info_get_max.restype   = ctypes.c_long
    _lib.snd_ctl_elem_value_get_integer.restype = ctypes.c_long

    _CARD_NAME = 'EVO4'
    _VOL_CTL   = b'EVO4  Playback Volume'

    def _open_ctl():
        for line in open('/proc/asound/cards'):
            if _CARD_NAME in line:
                m = re.match(r'\s*(\d+)', line)
                if m:
                    h = ctypes.c_void_p()
                    ret = _lib.snd_ctl_open(ctypes.byref(h), f'hw:{m.group(1)}'.encode(), 0)
                    if ret < 0:
                        raise OSError(f"snd_ctl_open failed: {ret}")
                    return h
        raise RuntimeError(f"ALSA card {_CARD_NAME!r} not found")

    def _find_vol_ctl(h):
        """Return (numid, min_db, max_db, max_step) for _VOL_CTL."""
        el = ctypes.c_void_p()
        _lib.snd_ctl_elem_list_malloc(ctypes.byref(el))
        _lib.snd_ctl_elem_list(h, el)
        count = _lib.snd_ctl_elem_list_get_count(el)
        _lib.snd_ctl_elem_list_alloc_space(el, count)
        _lib.snd_ctl_elem_list(h, el)
        numid = None
        for i in range(count):
            if _lib.snd_ctl_elem_list_get_name(el, i) == _VOL_CTL:
                numid = _lib.snd_ctl_elem_list_get_numid(el, i)
                break
        _lib.snd_ctl_elem_list_free_space(el)
        _lib.snd_ctl_elem_list_free(el)
        if numid is None:
            raise RuntimeError(f"ALSA control {_VOL_CTL!r} not found")

        eid = ctypes.c_void_p(); _lib.snd_ctl_elem_id_malloc(ctypes.byref(eid))
        _lib.snd_ctl_elem_id_set_numid(eid, numid)
        ei = ctypes.c_void_p(); _lib.snd_ctl_elem_info_malloc(ctypes.byref(ei))
        _lib.snd_ctl_elem_info_set_id(ei, eid)
        _lib.snd_ctl_elem_info(h, ei)
        max_step = int(_lib.snd_ctl_elem_info_get_max(ei))

        # TLV type 4 = SNDRV_CTL_TLVT_DB_MINMAX: [type, size, min_centidB, max_centidB]
        tlv = (ctypes.c_uint * 4)()
        _lib.snd_ctl_elem_tlv_read(h, eid, tlv, ctypes.sizeof(tlv))
        min_db = ctypes.c_int(tlv[2]).value / 100.0
        max_db = ctypes.c_int(tlv[3]).value / 100.0

        _lib.snd_ctl_elem_info_free(ei)
        _lib.snd_ctl_elem_id_free(eid)
        return numid, min_db, max_db, max_step

    _vol_cache = None

    def _vol_info():
        global _vol_cache
        if _vol_cache is None:
            h = _open_ctl()
            _vol_cache = _find_vol_ctl(h)
            _lib.snd_ctl_close(h)
        return _vol_cache

    def get_volume_dB(_device=None) -> float:
        numid, min_db, max_db, max_step = _vol_info()
        h = _open_ctl()
        eid = ctypes.c_void_p(); _lib.snd_ctl_elem_id_malloc(ctypes.byref(eid))
        _lib.snd_ctl_elem_id_set_numid(eid, numid)
        ev = ctypes.c_void_p(); _lib.snd_ctl_elem_value_malloc(ctypes.byref(ev))
        _lib.snd_ctl_elem_value_set_id(ev, eid)
        _lib.snd_ctl_elem_read(h, ev)
        step = _lib.snd_ctl_elem_value_get_integer(ev, 0)
        _lib.snd_ctl_elem_value_free(ev)
        _lib.snd_ctl_elem_id_free(eid)
        _lib.snd_ctl_close(h)
        return min_db + step / max_step * (max_db - min_db)

    def set_volume_dB(_device, db: float):
        numid, min_db, max_db, max_step = _vol_info()
        db = max(min_db, min(max_db, db))
        step = round((db - min_db) / (max_db - min_db) * max_step)
        h = _open_ctl()
        eid = ctypes.c_void_p(); _lib.snd_ctl_elem_id_malloc(ctypes.byref(eid))
        _lib.snd_ctl_elem_id_set_numid(eid, numid)
        ev = ctypes.c_void_p(); _lib.snd_ctl_elem_value_malloc(ctypes.byref(ev))
        _lib.snd_ctl_elem_value_set_id(ev, eid)
        _lib.snd_ctl_elem_read(h, ev)  # read first to preserve non-volume channels
        _lib.snd_ctl_elem_value_set_integer(ev, 0, step)  # L
        _lib.snd_ctl_elem_value_set_integer(ev, 1, step)  # R
        _lib.snd_ctl_elem_write(h, ev)
        _lib.snd_ctl_elem_value_free(ev)
        _lib.snd_ctl_elem_id_free(eid)
        _lib.snd_ctl_close(h)

else:
    # Windows: WinUSB driver required; claim_interface works without disrupting audio.
    from contextlib import contextmanager
    from usb.backend.libusb1 import get_backend
    import usb.core
    import usb.util

    USB_INTERFACE = 0x00

    @contextmanager
    def _claim(device, interface):
        usb.util.claim_interface(device, interface)
        yield
        usb.util.release_interface(device, interface)

    def get_volume_dB(device) -> float:
        with _claim(device, USB_INTERFACE):
            data = device.ctrl_transfer(
                bmRequestType=0xa1, bRequest=0x01,
                wValue=0x0000, wIndex=0x3B00, data_or_wLength=4)
        return int.from_bytes(data, byteorder='little', signed=True) / 256.0

    def set_volume_dB(device, db: float):
        assert -96.0 <= db <= 0.0, "db outside range <-96.0, 0.0>"
        db_fixed_point = int(db * 256.0)
        data = db_fixed_point.to_bytes(4, byteorder='little', signed=True)
        with _claim(device, USB_INTERFACE):
            device.ctrl_transfer(
                bmRequestType=0x21, bRequest=0x01,
                wValue=0x0000, wIndex=0x3B00, data_or_wLength=data)


def get_volume(device=None) -> int:
    return dB_to_volume_percent(get_volume_dB(device))


# ── CLI ───────────────────────────────────────────────────────────────────────

PARAMETERS = ['volume']

def parse_args():
    parser = argparse.ArgumentParser(description="Control Audient EVO4 settings.")
    subparsers = parser.add_subparsers(dest='action', required=True)

    get_parser = subparsers.add_parser('get', aliases=['g'], help='Get a device parameter.')
    get_parser.add_argument('parameter', choices=PARAMETERS)

    set_parser = subparsers.add_parser('set', aliases=['s'], help='Set a device parameter.')
    set_parser.add_argument('parameter', choices=PARAMETERS)
    set_parser.add_argument('value', type=str)

    args = parser.parse_args()

    if args.action in ('set', 's') and args.parameter == 'volume':
        try:
            args.value = int(args.value)
        except ValueError:
            parser.error("Volume value must be an integer.")
        if not (0 <= args.value <= 100):
            parser.error("Volume must be between 0 and 100.")

    return args

if __name__ == "__main__":
    args = parse_args()

    if sys.platform == 'linux':
        dev = None
    else:
        lib_path = os.environ.get('LIBUSB_PATH')
        backend = get_backend(find_library=lambda x: lib_path) if lib_path else get_backend()
        assert backend is not None, "libusb v1.0 not found"
        dev = usb.core.find(idVendor=AUDIENT_VENDOR_ID, idProduct=EVO4_ID, backend=backend)
        assert isinstance(dev, usb.core.Device), \
            f"Device vID:{AUDIENT_VENDOR_ID:#0x} pID:{EVO4_ID:#0x} not found"

    if args.action in ('get', 'g'):
        if args.parameter == 'volume':
            dB = get_volume_dB(dev)
            print(f"[GET] Volume: {dB_to_volume_percent(dB)} ({dB:.1f} dB)")
    elif args.action in ('set', 's'):
        if args.parameter == 'volume':
            set_volume_dB(dev, volume_percent_to_dB(args.value))
            print(f"[SET] Volume: {args.value}")
