## Handoff Summary: Approach 1 (for new session)

**Goal:** Make `audient.py` work on Windows without swapping drivers, by communicating
with the Audient vendor driver (`audientusbaudio.sys`) the same way the EVO app does.

**Device:** Audient EVO 4, VID `0x2708`, PID `0x0006`. USB composite device (IAD), but
the vendor driver claims the whole device at parent level — no composite child splitting.

**Current mechanism (PyUSB):** USB control transfer on EP0:
- `bmRequestType=0x21, bRequest=0x01, wIndex=0x3B00` (SET_CUR to Extension Unit 0x3B on IF0)
- `bmRequestType=0xA1, bRequest=0x01, wIndex=0x3B00` (GET_CUR from Extension Unit 0x3B)
- 4-byte signed int payload, little-endian, dB×256 fixed-point. Range: -96 to 0 dB → 0-100%
- Entity 0x3B is a **UAC2 Extension Unit** (vendor-defined), not a standard Feature Unit.
  This means it's NOT accessible via standard Windows audio APIs (no IAudioEndpointVolume etc.)

**What to implement:** A Windows-specific backend that avoids PyUSB/WinUSB entirely, using
ctypes to call Windows APIs that talk to the vendor driver directly.

**Likely mechanism:** `IOCTL_KS_PROPERTY` (`0x29000C`) — Windows Kernel Streaming API.
Audio WDM minidrivers (like `audientusbaudio.sys`) expose device controls via KS topology
nodes. The EVO app opens a KS pin/filter handle and sends KS property requests.

**Tracing tool:** [API Monitor](http://www.rohitab.com/apimonitor) (free, 32+64-bit)
1. Launch API Monitor
2. API filter: enable `Kernel Streaming` + `Windows Device and Driver Kit` (or just all)
3. Attach to the EVO4 app process
4. Change volume in the app → capture `DeviceIoControl` calls
5. Key data to extract from captured calls:
   - `CreateFile` → device path (e.g., `\\?\usb#vid_2708...`, or `\\.\audientusbaudio`, or a GUID path)
   - `DeviceIoControl` → IOCTL code (expect `0x29000C`) + full input buffer bytes
   - If no `DeviceIoControl`: look for `WinUsb_ControlTransfer` or named pipe calls

**Python implementation plan:**
```python
# pseudo-code for ctypes backend (fill in after tracing)
import ctypes, ctypes.wintypes

GENERIC_READ_WRITE = 0xC0000000
OPEN_EXISTING = 3
IOCTL_KS_PROPERTY = 0x29000C

handle = ctypes.windll.kernel32.CreateFileW(
    device_path, GENERIC_READ_WRITE,
    FILE_SHARE_READ | FILE_SHARE_WRITE, None,
    OPEN_EXISTING, 0, None
)
ctypes.windll.kernel32.DeviceIoControl(
    handle, IOCTL_KS_PROPERTY,
    ctypes.byref(in_buf), sizeof(in_buf),
    ctypes.byref(out_buf), sizeof(out_buf),
    ctypes.byref(bytes_returned), None
)
```

**Device path discovery (needed for CreateFile):**
```python
# Use SetupAPI to enumerate devices matching the audio device GUID
# GUID_DEVINTERFACE_AUDIO: {6994AD04-93EF-11D0-A3CC-00A0C9223196}
import win32com.client  # or use ctypes + setup32 API
```

**Code location:** `audient.py` — add a `WindowsKSBackend` class with `get_volume()` /
`set_volume()` methods, auto-selected when `sys.platform == 'win32'` and WinUSB is not active.

---

## Files to Modify

- `audient.py` — Add `WindowsKSBackend` class (Approach 1 only)

## Verification

- Device plays audio normally while Python script runs (no driver swap)
- `python audient.py volume get` returns correct value
- `python audient.py volume set 75` changes volume without interrupting audio
