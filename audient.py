import argparse
import os
import sys
import math
from contextlib import contextmanager

from usb.backend.libusb1 import get_backend
import usb.core


AUDIENT_VENDOR_ID = 0x2708
EVO4_ID = 0x0006
USB_INTERFACE = 0x00 # wIndex

@contextmanager
def detach_kernel_driver(device: usb.core.Device, interface: int):
    # Windows: expects WinUSB or such generic USB driver to be set
    if sys.platform == "win32":
        yield
        return
    # Linux: hot-swap auto-attached kernel driver
    was_kernel_driver_active = device.is_kernel_driver_active(interface)
    if was_kernel_driver_active:
        device.detach_kernel_driver(interface)
    yield
    if was_kernel_driver_active:
        device.attach_kernel_driver(interface)

@contextmanager
def claim_usb_interface(device: usb.core.Device, interface: int):
    with detach_kernel_driver(device, interface):
        usb.util.claim_interface(device, interface)
        yield
        usb.util.release_interface(device, interface)

def volume_percent_to_dB(volume:int) -> float:
    """Map volume 0-100 to dB -96.0-0.0 with a power curve anchored at 50 -> -20 dB."""
    # From: db = -96 * (1 - (volume/100)^n), solving n for 50 -> -20 dB:
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return -96.0 * (1.0 - (volume / 100.0) ** n)

def dB_to_volume_percent(db: float) -> int:
    """Inverse of volume_percent_to_dB: map dB -96.0-0.0 to volume 0-100."""
    db = max(-96.0, min(0.0, db))
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return round(100.0 * (1.0 + db / 96.0) ** (1.0 / n))

def set_volume_dB(device: usb.core.Device, db: float):
    assert -96.0 <= db <= 0.0, "db outside range <-96.0, 0.0>"
    db_fixed_point = int(db * 256.0)
    data = db_fixed_point.to_bytes(4, byteorder='little', signed=True)
    with claim_usb_interface(device, USB_INTERFACE):
        res = device.ctrl_transfer(
            bmRequestType=0x21,
            bRequest=0x01,
            wValue=0x0000,
            wIndex=0x3B00,
            data_or_wLength=data
        )
        if res is None:
            print("Unable to set volume")

def get_volume_dB(device: usb.core.Device) -> float:
    with claim_usb_interface(device, USB_INTERFACE):
        data = device.ctrl_transfer(
            bmRequestType=0xa1,
            bRequest=0x01,
            wValue=0x0000,
            wIndex=0x3B00,
            data_or_wLength=4
        )
    db_fixed_point = int.from_bytes(data, byteorder='little', signed=True)
    return db_fixed_point / 256.0


def get_volume(device: usb.core.Device) -> int:
    return dB_to_volume_percent(get_volume_dB(device))

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

    lib_path = os.environ.get('LIBUSB_PATH')
    backend = get_backend(find_library=lambda x: lib_path) if lib_path else get_backend()
    assert backend is not None, "libusb v1.0 not found"

    dev = usb.core.find(idVendor=AUDIENT_VENDOR_ID, idProduct=EVO4_ID, backend=backend)
    assert isinstance(dev, usb.core.Device), f"Device vID:{AUDIENT_VENDOR_ID:#0x} pID:{EVO4_ID:#0x} not found"

    if args.action in ('get', 'g'):
        if args.parameter == 'volume':
            dB = get_volume_dB(dev)
            print(f"[GET] Volume: {dB_to_volume_percent(dB)} ({dB:.1f} dB)")
    elif args.action in ('set', 's'):
        if args.parameter == 'volume':
            set_volume_dB(dev, volume_percent_to_dB(args.value))
            print(f"[SET] Volume: {args.value}")
