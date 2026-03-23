"""Python wrapper for /dev/evo4 ioctl — raw USB control transfers via kernel module."""

import fcntl
import struct

# Must match struct evo4_ctrl_xfer in evo4_raw.c
# Layout: u8 bRequestType, u8 bRequest, u16 wValue, u16 wIndex, u16 wLength, u8[256] data
_XFER_FMT = "<BBHHH256s"
_XFER_SIZE = struct.calcsize(_XFER_FMT)

# _IOWR('E', 0, struct evo4_ctrl_xfer) — must match the kernel module's ioctl number
# ioctl encoding: dir(2) | size(14) | type(8) | nr(8)
# dir = _IOC_READ|_IOC_WRITE = 3, size = _XFER_SIZE, type = 'E' (0x45), nr = 0
_IOC_WRITE = 1
_IOC_READ = 2
_IOC_DIR = _IOC_READ | _IOC_WRITE
EVO4_CTRL_TRANSFER = (_IOC_DIR << 30) | (_XFER_SIZE << 16) | (0x45 << 8) | 0

# USB Audio Class constants
REQTYPE_SET = 0x21  # Host->Device, Class, Interface
REQTYPE_GET = 0xA1  # Device->Host, Class, Interface
REQ_CUR = 0x01  # SET_CUR / GET_CUR

DEV_PATH = "/dev/evo4"


def ctrl_transfer(fd, bRequestType, bRequest, wValue, wIndex, data=b"", length=None):
    """Send a USB control transfer via the evo4_raw kernel module.

    For SET (OUT) transfers, pass data bytes. length is inferred from data.
    For GET (IN) transfers, pass length (number of bytes to read). Returns bytes.
    """
    if bRequestType & 0x80:  # IN transfer
        wLength = length if length is not None else 0
        payload = b"\x00" * 256
    else:  # OUT transfer
        wLength = len(data)
        payload = data.ljust(256, b"\x00")

    buf = bytearray(
        struct.pack(_XFER_FMT, bRequestType, bRequest, wValue, wIndex, wLength, payload)
    )

    fcntl.ioctl(fd, EVO4_CTRL_TRANSFER, buf)

    if bRequestType & 0x80:
        # Unpack response — kernel updated wLength to actual bytes received
        _, _, _, _, resp_len, resp_data = struct.unpack(_XFER_FMT, buf)
        return bytes(resp_data[:resp_len])
    return None


def open_device():
    """Open /dev/evo4 for ioctl access. Use as context manager."""
    return open(DEV_PATH, "rb")


def get_cur(fd, wValue, wIndex, length):
    """GET_CUR request — read current value from a USB Audio unit."""
    return ctrl_transfer(fd, REQTYPE_GET, REQ_CUR, wValue, wIndex, length=length)


def set_cur(fd, wValue, wIndex, data):
    """SET_CUR request — write a value to a USB Audio unit."""
    ctrl_transfer(fd, REQTYPE_SET, REQ_CUR, wValue, wIndex, data=data)
