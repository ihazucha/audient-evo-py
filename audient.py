#!python

import usb.core
import usb.util

AUDIENT_VENDOR_ID = 0x2708
EVO4_ID = 0x0006


if __name__ == "__main__":
    dev = usb.core.find(idVendor=AUDIENT_VENDOR_ID, idProduct=EVO4_ID)
    print(dev)
