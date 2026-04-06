"""Shared test fixtures for device-agnostic testing."""

import pytest

from evo.devices import DEVICES, DeviceSpec, detect_devices


def pytest_addoption(parser):
    parser.addoption(
        "--device",
        choices=["evo4", "evo8", "auto"],
        default="auto",
        help="Device to test: evo4, evo8, or auto (detect from /dev/evo*).",
    )


@pytest.fixture(scope="session")
def device_spec(request) -> DeviceSpec:
    """Resolve the device spec to test against."""
    choice = request.config.getoption("--device")
    if choice != "auto":
        return DEVICES[choice]
    found = detect_devices()
    if len(found) == 1:
        return found[0]
    if len(found) == 0:
        pytest.skip("No EVO device detected (use --device to specify)")
    names = ", ".join(s.name for s in found)
    pytest.skip(f"Multiple devices detected ({names}) - use --device to select one")


@pytest.fixture(scope="module")
def evo(device_spec):
    """EVOController instance for the target device."""
    from evo.controller import EVOController
    return EVOController(device_spec)
