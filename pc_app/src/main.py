"""
main.py — Pico Oscilloscope CLI

Command-line interface for the Pico Oscilloscope.
Supports capture, monitoring, CSV export, and JSON status output.

Usage:
    python main.py status --port COM3
    python main.py capture --port COM3 --mode hat --duration 5 --output data.csv
    python main.py monitor --port COM3 --mode hat
    python main.py config --port COM3 --mode oscilloscope --trigger rising --channel 0 --level 2048
"""

import argparse
import csv
import json
import signal
import sys
import time
from datetime import datetime
from typing import Optional

from serial_reader import (
    SerialReader,
    MODE_HAT,
    MODE_OSCILLOSCOPE,
    MSG_PIN_DATA,
    MSG_ADC_DATA,
    MSG_TRIGGER,
    MSG_STATUS,
    MSG_ERROR,
)

# GPIO pin names for display
HAT_PIN_COUNT = 30
ADC_CHANNELS = 4
ADC_GPIO_START = 26

# Interrupt flag for clean shutdown
running = True


def signal_handler(sig, frame):
    global running
    running = False


signal.signal(signal.SIGINT, signal_handler)


def format_pin_state(snapshot: int, pin_count: int = HAT_PIN_COUNT) -> str:
    """Format a GPIO snapshot as a binary string."""
    return "".join(
        str((snapshot >> i) & 1) for i in range(pin_count - 1, -1, -1)
    )


def pin_snapshot_to_dict(snapshot: int) -> dict:
    """Convert GPIO snapshot to dict of pin: state."""
    result = {}
    for i in range(HAT_PIN_COUNT):
        result[f"GPIO{i}"] = (snapshot >> i) & 1
    return result


def cmd_status(args):
    """Print device status as JSON."""
    reader = SerialReader(args.port)
    if not reader.connect():
        print(json.dumps({"status": "error", "message": "Connection failed"}))
        sys.exit(1)

    info = {
        "status": "connected",
        "port": args.port,
        "timestamp": datetime.now().isoformat(),
    }
    print(json.dumps(info))
    reader.disconnect()


def cmd_capture(args):
    """Capture data for a specified duration and save to CSV."""
    mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE
    duration = args.duration
    output = args.output

    reader = SerialReader(args.port)
    if not reader.connect():
        print("Error: Connection failed", file=sys.stderr)
        sys.exit(1)

    # Set mode
    if not reader.set_mode(mode):
        print("Error: Failed to set mode", file=sys.stderr)
        reader.disconnect()
        sys.exit(1)

    # Configure trigger if in oscilloscope mode
    if mode == MODE_OSCILLOSCOPE and args.trigger != "none":
        trigger_map = {"rising": 1, "falling": 2, "both": 3}
        trig_mode = trigger_map.get(args.trigger, 0)
        reader.configure_trigger(args.channel, trig_mode, args.level)

    # Start sampling
    if not reader.start_sampling():
        print("Error: Failed to start sampling", file=sys.stderr)
        reader.disconnect()
        sys.exit(1)

    # Collect data
    pin_data = []
    adc_data = []
    start_time = time.time()
    sample_index = 0

    while running and (time.time() - start_time) < duration:
        result = reader.receive_frame(timeout=0.1)
        if result is None:
            continue

        msg_type, payload = result
        timestamp = time.time() - start_time

        if msg_type == MSG_PIN_DATA:
            snapshots = SerialReader.decode_pin_data(payload)
            for snap in snapshots:
                pin_data.append({
                    "index": sample_index,
                    "timestamp": timestamp,
                    "gpio_raw": snap,
                })
                sample_index += 1

        elif msg_type == MSG_ADC_DATA:
            samples = SerialReader.decode_adc_data(payload)
            for i, val in enumerate(samples):
                ch = i % ADC_CHANNELS
                adc_data.append({
                    "index": sample_index,
                    "timestamp": timestamp,
                    "channel": ch,
                    "raw": val,
                    "voltage": SerialReader.adc_to_voltage(val),
                })
                sample_index += 1

    # Stop
    reader.stop_sampling()
    reader.disconnect()

    # Write CSV
    if output:
        _write_capture_csv(output, mode, pin_data, adc_data)
        print(f"Captured {sample_index} samples to {output}")
    else:
        # Write to stdout
        _write_capture_stdout(mode, pin_data, adc_data)


def _write_capture_csv(path: str, mode: int, pin_data: list, adc_data: list):
    """Write captured data to a CSV file."""
    with open(path, "w", newline="") as f:
        if mode == MODE_HAT:
            writer = csv.writer(f)
            header = ["index", "timestamp"] + [f"GPIO{i}" for i in range(HAT_PIN_COUNT)]
            writer.writerow(header)
            for entry in pin_data:
                row = [entry["index"], f"{entry['timestamp']:.6f}"]
                snap = entry["gpio_raw"]
                row.extend([(snap >> i) & 1 for i in range(HAT_PIN_COUNT)])
                writer.writerow(row)
        else:
            writer = csv.writer(f)
            writer.writerow(["index", "timestamp", "channel", "raw", "voltage"])
            for entry in adc_data:
                writer.writerow([
                    entry["index"],
                    f"{entry['timestamp']:.6f}",
                    entry["channel"],
                    entry["raw"],
                    f"{entry['voltage']:.4f}",
                ])


def _write_capture_stdout(mode: int, pin_data: list, adc_data: list):
    """Write captured data to stdout in CSV format."""
    writer = csv.writer(sys.stdout)
    if mode == MODE_HAT:
        writer.writerow(["index", "timestamp", "gpio_raw"])
        for entry in pin_data:
            writer.writerow([
                entry["index"],
                f"{entry['timestamp']:.6f}",
                f"0x{entry['gpio_raw']:08X}",
            ])
    else:
        writer.writerow(["index", "timestamp", "channel", "raw", "voltage"])
        for entry in adc_data:
            writer.writerow([
                entry["index"],
                f"{entry['timestamp']:.6f}",
                entry["channel"],
                entry["raw"],
                f"{entry['voltage']:.4f}",
            ])


def cmd_monitor(args):
    """Live monitoring mode — prints data to stdout continuously."""
    mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE

    reader = SerialReader(args.port)
    if not reader.connect():
        print("Error: Connection failed", file=sys.stderr)
        sys.exit(1)

    if not reader.set_mode(mode):
        print("Error: Failed to set mode", file=sys.stderr)
        reader.disconnect()
        sys.exit(1)

    if not reader.start_sampling():
        print("Error: Failed to start sampling", file=sys.stderr)
        reader.disconnect()
        sys.exit(1)

    try:
        while running:
            result = reader.receive_frame(timeout=0.1)
            if result is None:
                continue

            msg_type, payload = result

            if args.format == "json":
                _print_json(msg_type, payload)
            else:
                _print_text(msg_type, payload, mode)

    finally:
        reader.stop_sampling()
        reader.disconnect()


def _print_json(msg_type: int, payload: bytes):
    """Print frame data as JSON (one object per line)."""
    ts = datetime.now().isoformat()

    if msg_type == MSG_PIN_DATA:
        snapshots = SerialReader.decode_pin_data(payload)
        for snap in snapshots:
            obj = {"type": "pin", "timestamp": ts, "gpio_raw": snap,
                   "pins": pin_snapshot_to_dict(snap)}
            print(json.dumps(obj), flush=True)

    elif msg_type == MSG_ADC_DATA:
        samples = SerialReader.decode_adc_data(payload)
        for i, val in enumerate(samples):
            ch = i % ADC_CHANNELS
            obj = {"type": "adc", "timestamp": ts, "channel": ch,
                   "raw": val, "voltage": round(SerialReader.adc_to_voltage(val), 4)}
            print(json.dumps(obj), flush=True)

    elif msg_type == MSG_TRIGGER:
        print(json.dumps({"type": "trigger", "timestamp": ts}), flush=True)


def _print_text(msg_type: int, payload: bytes, mode: int):
    """Print frame data as human-readable text."""
    if msg_type == MSG_PIN_DATA:
        snapshots = SerialReader.decode_pin_data(payload)
        for snap in snapshots:
            print(f"PIN 0x{snap:08X} {format_pin_state(snap)}", flush=True)

    elif msg_type == MSG_ADC_DATA:
        samples = SerialReader.decode_adc_data(payload)
        for i, val in enumerate(samples):
            ch = i % ADC_CHANNELS
            voltage = SerialReader.adc_to_voltage(val)
            print(f"ADC CH{ch} {val:4d} {voltage:.3f}V", flush=True)

    elif msg_type == MSG_TRIGGER:
        print("TRIGGER", flush=True)


def cmd_config(args):
    """Send configuration commands to the Pico."""
    reader = SerialReader(args.port)
    if not reader.connect():
        print(json.dumps({"status": "error", "message": "Connection failed"}))
        sys.exit(1)

    success = True

    if args.mode:
        mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE
        if not reader.set_mode(mode):
            success = False

    if args.trigger and args.trigger != "none":
        trigger_map = {"rising": 1, "falling": 2, "both": 3}
        trig_mode = trigger_map.get(args.trigger, 0)
        if not reader.configure_trigger(args.channel, trig_mode, args.level):
            success = False

    result = {"status": "ok" if success else "error"}
    print(json.dumps(result))
    reader.disconnect()


def main():
    parser = argparse.ArgumentParser(
        prog="pico_oscilloscope",
        description="Pico Oscilloscope — CLI for capture and monitoring",
    )
    parser.add_argument("--port", "-p", required=True, help="Serial port (e.g., COM3, /dev/ttyACM0)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    sub_status = subparsers.add_parser("status", help="Get device status (JSON)")

    # capture
    sub_capture = subparsers.add_parser("capture", help="Capture data to CSV")
    sub_capture.add_argument("--mode", "-m", choices=["hat", "oscilloscope"], default="hat",
                             help="Operating mode")
    sub_capture.add_argument("--duration", "-d", type=float, default=5.0,
                             help="Capture duration in seconds")
    sub_capture.add_argument("--output", "-o", type=str, default=None,
                             help="Output CSV file (stdout if omitted)")
    sub_capture.add_argument("--trigger", "-t", choices=["none", "rising", "falling", "both"],
                             default="none", help="Trigger mode (osc mode only)")
    sub_capture.add_argument("--channel", "-c", type=int, default=0,
                             help="Trigger channel (0-3)")
    sub_capture.add_argument("--level", "-l", type=int, default=2048,
                             help="Trigger level (0-4095)")

    # monitor
    sub_monitor = subparsers.add_parser("monitor", help="Live monitoring (continuous)")
    sub_monitor.add_argument("--mode", "-m", choices=["hat", "oscilloscope"], default="hat",
                             help="Operating mode")
    sub_monitor.add_argument("--format", "-f", choices=["text", "json"], default="text",
                             help="Output format")

    # config
    sub_config = subparsers.add_parser("config", help="Configure device")
    sub_config.add_argument("--mode", "-m", choices=["hat", "oscilloscope"],
                            help="Set operating mode")
    sub_config.add_argument("--trigger", "-t", choices=["none", "rising", "falling", "both"],
                            help="Trigger mode")
    sub_config.add_argument("--channel", "-c", type=int, default=0,
                            help="Trigger channel (0-3)")
    sub_config.add_argument("--level", "-l", type=int, default=2048,
                            help="Trigger level (0-4095)")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "capture": cmd_capture,
        "monitor": cmd_monitor,
        "config": cmd_config,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
