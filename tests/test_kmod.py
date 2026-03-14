"""Unit tests for kmod — the Python wrapper for /dev/evo4 ioctl.

These tests mock the ioctl and file I/O so they run without hardware.
They verify struct packing, ioctl number calculation, and transfer logic.
"""

import struct
from unittest.mock import patch, MagicMock

import pytest

from evo4 import kmod


# --- ioctl number ---

class TestIoctlNumber:
    def test_ioctl_direction_bits(self):
        """_IOWR means both read and write — direction bits should be 0b11."""
        direction = (kmod.EVO4_CTRL_TRANSFER >> 30) & 0x3
        assert direction == 3  # _IOC_READ | _IOC_WRITE

    def test_ioctl_type_is_E(self):
        """Type field should be 'E' (0x45)."""
        ioc_type = (kmod.EVO4_CTRL_TRANSFER >> 8) & 0xFF
        assert ioc_type == 0x45

    def test_ioctl_nr_is_zero(self):
        """Command number should be 0."""
        nr = kmod.EVO4_CTRL_TRANSFER & 0xFF
        assert nr == 0

    def test_ioctl_size_matches_struct(self):
        """Size field should match the packed struct size."""
        size = (kmod.EVO4_CTRL_TRANSFER >> 16) & 0x3FFF
        assert size == kmod._XFER_SIZE


# --- struct packing ---

class TestStructPacking:
    def test_xfer_size(self):
        """Struct should be 8 bytes header + 256 bytes data = 264."""
        assert kmod._XFER_SIZE == 264

    def test_pack_unpack_roundtrip(self):
        """Packing then unpacking should return the same values."""
        rt, rq, wv, wi, wl = 0x21, 0x01, 0x0200, 0x0A00, 2
        payload = b"\x42\x43" + b"\x00" * 254

        buf = struct.pack(kmod._XFER_FMT, rt, rq, wv, wi, wl, payload)
        rt2, rq2, wv2, wi2, wl2, data2 = struct.unpack(kmod._XFER_FMT, buf)

        assert (rt2, rq2, wv2, wi2, wl2) == (rt, rq, wv, wi, wl)
        assert data2[:2] == b"\x42\x43"

    def test_data_field_is_256_bytes(self):
        """Data field in the format string should pad/truncate to 256."""
        payload = b"\xff" * 256
        buf = struct.pack(kmod._XFER_FMT, 0, 0, 0, 0, 0, payload)
        _, _, _, _, _, data = struct.unpack(kmod._XFER_FMT, buf)
        assert len(data) == 256


# --- ctrl_transfer ---

class TestCtrlTransferOut:
    """SET (OUT) transfers — bRequestType bit 7 = 0."""

    def test_out_packs_data_and_calls_ioctl(self):
        fd = MagicMock()
        data = b"\x10\x20"

        with patch("fcntl.ioctl") as mock_ioctl:
            result = kmod.ctrl_transfer(
                fd, 0x21, 0x01, 0x0200, 0x0A00, data=data
            )

        mock_ioctl.assert_called_once()
        call_args = mock_ioctl.call_args
        assert call_args[0][0] is fd
        assert call_args[0][1] == kmod.EVO4_CTRL_TRANSFER

        # Verify the packed buffer contains the correct header
        buf = call_args[0][2]
        rt, rq, wv, wi, wl, payload = struct.unpack(kmod._XFER_FMT, bytes(buf))
        assert (rt, rq, wv, wi, wl) == (0x21, 0x01, 0x0200, 0x0A00, 2)
        assert payload[:2] == b"\x10\x20"
        assert result is None

    def test_out_data_padded_to_256(self):
        fd = MagicMock()

        with patch("fcntl.ioctl") as mock_ioctl:
            kmod.ctrl_transfer(fd, 0x21, 0x01, 0, 0, data=b"\xAA")

        buf = mock_ioctl.call_args[0][2]
        _, _, _, _, _, payload = struct.unpack(kmod._XFER_FMT, bytes(buf))
        assert payload[0:1] == b"\xAA"
        assert payload[1:] == b"\x00" * 255


class TestCtrlTransferIn:
    """GET (IN) transfers — bRequestType bit 7 = 1."""

    def _simulate_in_response(self, resp_data, resp_len=None):
        """Create a mock ioctl that writes a response into the buffer."""
        if resp_len is None:
            resp_len = len(resp_data)

        def side_effect(fd, cmd, buf):
            # Simulate kernel filling in the response
            padded = resp_data.ljust(256, b"\x00")
            # Repack with updated wLength and data
            rt, rq, wv, wi, _, _ = struct.unpack(kmod._XFER_FMT, bytes(buf))
            response = struct.pack(kmod._XFER_FMT, rt, rq, wv, wi, resp_len, padded)
            buf[:] = bytearray(response)

        return side_effect

    def test_in_returns_bytes(self):
        fd = MagicMock()
        resp = b"\xDE\xAD"

        with patch("fcntl.ioctl", side_effect=self._simulate_in_response(resp)):
            result = kmod.ctrl_transfer(
                fd, 0xA1, 0x01, 0x0200, 0x0A00, length=2
            )

        assert result == b"\xDE\xAD"

    def test_in_respects_response_length(self):
        fd = MagicMock()
        # Kernel returns 4 bytes even though we requested more
        resp = b"\x01\x02\x03\x04"

        with patch("fcntl.ioctl", side_effect=self._simulate_in_response(resp, 4)):
            result = kmod.ctrl_transfer(
                fd, 0xA1, 0x01, 0, 0, length=8
            )

        assert result == b"\x01\x02\x03\x04"

    def test_in_empty_response(self):
        fd = MagicMock()

        with patch("fcntl.ioctl", side_effect=self._simulate_in_response(b"", 0)):
            result = kmod.ctrl_transfer(
                fd, 0xA1, 0x01, 0, 0, length=4
            )

        assert result == b""


# --- convenience functions ---

class TestGetCur:
    def test_calls_ctrl_transfer_with_get_params(self):
        fd = MagicMock()

        with patch("evo4.kmod.ctrl_transfer", return_value=b"\x42\x00") as mock_ct:
            result = kmod.get_cur(fd, wValue=0x0200, wIndex=0x0A00, length=2)

        mock_ct.assert_called_once_with(
            fd, kmod.REQTYPE_GET, kmod.REQ_CUR,
            0x0200, 0x0A00, length=2
        )
        assert result == b"\x42\x00"


class TestSetCur:
    def test_calls_ctrl_transfer_with_set_params(self):
        fd = MagicMock()

        with patch("evo4.kmod.ctrl_transfer") as mock_ct:
            kmod.set_cur(fd, wValue=0x0200, wIndex=0x0A00, data=b"\x10\x20")

        mock_ct.assert_called_once_with(
            fd, kmod.REQTYPE_SET, kmod.REQ_CUR,
            0x0200, 0x0A00, data=b"\x10\x20"
        )


class TestOpenDevice:
    def test_opens_dev_evo4(self):
        with patch("builtins.open", return_value=MagicMock()) as mock_open:
            kmod.open_device()
        mock_open.assert_called_once_with("/dev/evo4", "rb")


# --- constants ---

class TestConstants:
    def test_reqtype_set_is_host_to_device_class_interface(self):
        assert kmod.REQTYPE_SET == 0x21

    def test_reqtype_get_is_device_to_host_class_interface(self):
        assert kmod.REQTYPE_GET == 0xA1

    def test_req_cur(self):
        assert kmod.REQ_CUR == 0x01
