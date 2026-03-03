# CLAUDE.md

## Project goals

- Multi-platform python control script for Audient EVO 4 sound mixer that:
  - allows device control and settings polling using SET/GET USB requests
  - does not interrupt ongoing audio transmission
- For functinality and overall project details read @./README.md

## Running the script

```bash
# Activate venv first
.venv/Scripts/activate

# Example: set volume (0-100)
python audient.py --volume 75
```

## Architecture

- Python script `audient.py` (possibly a small library).
  - communicates with EVO4 USB interface via direct USB control transfers using PyUSB/libusb
- For Windows development, a helper `driver_swap.ps1` is used to toggle between the Audient vendor driver and WinUSB (required on Windows to allow PyUSB access).
