#!/usr/bin/env python3
"""
Extract relevant USB control transfer fields from Wireshark/USBPcap JSON exports.
Filters to only host→device setup packets and extracts protocol-relevant fields.
"""

import json
from pathlib import Path


def extract_packet(packet):
    """
    Extract relevant fields from a USBPcap packet.
    Returns None if packet should be skipped (no Setup Data = not a setup packet).
    """
    source = packet.get("_source", {})
    layers = source.get("layers", {})

    # Only process setup stage packets (control_stage == "0")
    if "Setup Data" not in layers:
        return None

    setup = layers["Setup Data"]
    usb = layers.get("usb", {})
    frame = layers.get("frame", {})

    # Determine direction from irp_info
    irp_info_tree = usb.get("usb.irp_info_tree", {})
    direction_val = irp_info_tree.get("usb.irp_info.direction", "0")
    direction = "host→device" if direction_val == "0" else "device→host"

    # Extract Setup Data fields
    wvalue_tree = setup.get("usbaudio.wValue_tree", {})
    windex_tree = setup.get("usbaudio.wIndex_tree", {})

    return {
        "frame_number": frame.get("frame.number"),
        "frame_time": frame.get("frame.time"),
        "direction": direction,
        "transfer_type": usb.get("usb.transfer_type"),
        "bmRequestType": setup.get("usb.bmRequestType"),
        "bRequest": setup.get("usbaudio.bRequest"),
        "wValue": setup.get("usbaudio.wValue"),
        "wValue_channel": wvalue_tree.get("usbaudio.wValue.channel_number"),
        "wIndex": setup.get("usbaudio.wIndex"),
        "wIndex_interface": windex_tree.get("usbaudio.wIndex.interface"),
        "wIndex_entity_id": windex_tree.get("usbaudio.wIndex.entity_id"),
        "wLength": setup.get("usbaudio.wLength"),
        "data_fragment": setup.get("usb.data_fragment"),
    }


def process_file(input_path, output_path):
    """Process a single JSON file and write cherrypicked output."""
    with open(input_path, "r") as f:
        packets = json.load(f)

    cherrypicked = []
    for packet in packets:
        extracted = extract_packet(packet)
        if extracted is not None:
            cherrypicked.append(extracted)

    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(cherrypicked, f, indent=2)

    return len(packets), len(cherrypicked)


def main():
    usbpcap_dir = Path(__file__).parent
    output_dir = usbpcap_dir / "cherrypicked"

    total_input = 0
    total_output = 0

    for json_file in sorted(usbpcap_dir.glob("*.json")):
        # Skip cherrypicked directory
        if json_file.name.startswith("cherrypicked"):
            continue

        output_file = output_dir / json_file.name
        try:
            input_count, output_count = process_file(json_file, output_file)
            total_input += input_count
            total_output += output_count
            print(f"{json_file.name}: {input_count} packets → {output_count} cherrypicked")
        except Exception as e:
            print(f"ERROR processing {json_file.name}: {e}")

    print(f"\nTotal: {total_input} packets → {total_output} cherrypicked")


if __name__ == "__main__":
    main()
