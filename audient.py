#!python

from usb.backend.libusb1 import get_backend
import usb.core

AUDIENT_VENDOR_ID = 0x2708
EVO4_ID = 0x0006

def set_volume(dev: usb.core.Device, db: int):
    assert -96 <= db <= 0
    payload = db.to_bytes(2, byteorder='little', signed=True)
    res = dev.ctrl_transfer(
        bmRequestType=0x21,
        bRequest=0x01,
        wValue=0x0000,
        wIndex=0x0C02,
        data_or_wLength=payload
    )
    return res

if __name__ == "__main__":
    backend = get_backend(find_library=lambda x: "./libusb-1.0.dll")
    assert backend is not None, "libusb not found."

    dev = usb.core.find(idVendor=AUDIENT_VENDOR_ID, idProduct=EVO4_ID, backend=backend)
    assert isinstance(dev, usb.core.Device), "Device not found."

    res = set_volume(dev, -50)
    print(res)
