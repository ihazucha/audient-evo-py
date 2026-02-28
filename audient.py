#!python

from usb.backend.libusb1 import get_backend
import usb.core
import argparse

import sys
import math
from contextlib import contextmanager

AUDIENT_VENDOR_ID = 0x2708
EVO4_ID = 0x0006
USB_INTERFACE = 0x00 # wIndex

@contextmanager
def claim_usb_interface(device:usb.core.Device, interface:int):
    try:
        device.set_interface_altsetting(interface=interface)
        yield
    finally:
        pass

# @contextmanager
# def claim_usb_interface(device: usb.core.Device, interface: int):
#     was_kernel_driver_active = device.is_kernel_driver_active(interface)
#     if was_kernel_driver_active:
#         device.detach_kernel_driver(interface)
#     usb.util.claim_interface(device, interface)
#     yield
#     usb.util.release_interface(device, interface)
#     if was_kernel_driver_active:
#         device.attach_kernel_driver(interface)

def volume_percent_to_dB(volume:int) -> float:
    """Map volume 0-100 to dB -96.0-0.0 with a power curve anchored at 50 -> -20 dB."""
    # From: db = -96 * (1 - (volume/100)^n), solving n for 50 -> -20 dB:
    n = math.log(1.0 - 20.0 / 96.0) / math.log(0.5)
    return -96.0 * (1.0 - (volume / 100.0) ** n)

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

def parse_args():
    parser = argparse.ArgumentParser(description="Control Audient EVO4 settings.")
    parser.add_argument(
        "-v", "--volume",
        type=int,
        metavar="VOLUME",
        required=True,
        help="Set the output volume (0-100)."
    )

    class Args(argparse.Namespace):
        volume: int = 0

    args = parser.parse_args(namespace=Args())
    if not (0 <= args.volume <= 100):
        parser.error("Volume must be between 0 and 100.")

    return args

if __name__ == "__main__":
    args = parse_args()

    if sys.platform == "win32":
        backend = get_backend(find_library=lambda x: "./libusb-1.0.dll")
    else:
        backend = get_backend()
    assert backend is not None, "libusb v1.0 not found"

    dev = usb.core.find(idVendor=AUDIENT_VENDOR_ID, idProduct=EVO4_ID, backend=backend)
    assert isinstance(dev, usb.core.Device), f"Device vID:{AUDIENT_VENDOR_ID:#0x} pID:{EVO4_ID:#0x} not found"

    dB = volume_percent_to_dB(args.volume)
    res = set_volume_dB(dev, dB)
    print(res)
