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
from pathlib import Path
import re
import signal
import sys
import time
from datetime import datetime
from protocol_analyzer import decode_dshot, decode_i2c, decode_spi, decode_uart, load_capture_csv
from serial_reader import (
    SerialReader,
    MODE_HAT,
    MODE_OSCILLOSCOPE,
    MSG_PIN_DATA,
    MSG_ADC_DATA,
    MSG_TRIGGER,
    MSG_PIN_BATCH,
    MSG_ADC_BATCH,
    MSG_STATUS,
    MSG_ERROR,
    STATUS_OVERFLOW,
)

# GPIO pin names for display
HAT_PIN_COUNT = 30
ADC_CHANNELS = 4
ADC_GPIO_START = 26
TIME_SCALE_PS = 1_000_000_000_000
DIGITAL_EXPORT_FULL = "full"
DIGITAL_EXPORT_EDGE = "edge"

# Interrupt flag for clean shutdown
running = True


def signal_handler(sig, frame):
    global running
    running = False


signal.signal(signal.SIGINT, signal_handler)


def batch_timestamp_seconds(start_time_ps: int, index: int, interval_ps: int) -> float:
    """Convert a batch-relative timestamp to seconds."""
    return (start_time_ps + index * interval_ps) / 1_000_000_000_000.0


def seconds_to_picoseconds(seconds: float) -> int:
    """Convert seconds to picoseconds."""
    return int(round(seconds * TIME_SCALE_PS))


def picoseconds_to_seconds(timestamp_ps: int) -> float:
    """Convert picoseconds to seconds."""
    return timestamp_ps / TIME_SCALE_PS


def entry_timestamp_ps(entry: dict) -> int:
    """Return the exact timestamp for a capture entry."""
    if "timestamp_ps" in entry:
        return int(entry["timestamp_ps"])
    return seconds_to_picoseconds(float(entry["timestamp"]))


def pin_entry_raw_sample_index(entry: dict) -> int:
    """Return the raw sample index for a digital capture entry."""
    if "raw_sample_index" in entry:
        return int(entry["raw_sample_index"])
    if "sample_index" in entry:
        return int(entry["sample_index"])
    return int(entry["index"])


def compress_pin_data(pin_data: list[dict]) -> list[dict]:
    """Collapse digital samples to the first row plus rows where GPIO state changes."""
    compressed: list[dict] = []
    previous_snapshot = None
    previous_timestamp_ps = None
    previous_raw_sample_index = None

    for entry in pin_data:
        snapshot = entry["gpio_raw"]
        raw_sample_index = pin_entry_raw_sample_index(entry)
        timestamp_ps = entry_timestamp_ps(entry)

        if previous_snapshot is not None and snapshot == previous_snapshot:
            continue

        delta_samples = 0 if previous_raw_sample_index is None else raw_sample_index - previous_raw_sample_index
        delta_time_ps = 0 if previous_timestamp_ps is None else timestamp_ps - previous_timestamp_ps
        changed_mask = 0 if previous_snapshot is None else snapshot ^ previous_snapshot

        compressed.append({
            "index": len(compressed),
            "raw_sample_index": raw_sample_index,
            "timestamp": picoseconds_to_seconds(timestamp_ps),
            "timestamp_ps": timestamp_ps,
            "delta_samples": delta_samples,
            "delta_time_ps": delta_time_ps,
            "gpio_raw": snapshot,
            "changed_mask": changed_mask,
        })

        previous_snapshot = snapshot
        previous_timestamp_ps = timestamp_ps
        previous_raw_sample_index = raw_sample_index

    return compressed


def format_duration_ps(duration_ps: int) -> str:
    """Format a picosecond duration using a readable unit."""
    absolute_ps = abs(duration_ps)

    if absolute_ps >= 1_000_000_000_000:
        return f"{duration_ps / 1_000_000_000_000:.6f}s"
    if absolute_ps >= 1_000_000_000:
        return f"{duration_ps / 1_000_000_000:.3f}ms"
    if absolute_ps >= 1_000_000:
        return f"{duration_ps / 1_000_000:.3f}us"
    if absolute_ps >= 1_000:
        return f"{duration_ps / 1_000:.3f}ns"
    return f"{duration_ps}ps"


def capture_entries_span_ps(entries: list[dict]) -> int:
    """Return the measured span covered by a capture stream."""
    if len(entries) < 2:
        return 0
    return max(0, entry_timestamp_ps(entries[-1]) - entry_timestamp_ps(entries[0]))


def new_batch_stream_stats(name: str) -> dict:
    """Create overflow and batch-gap tracking state for one stream."""
    return {
        "name": name,
        "batch_count": 0,
        "previous_batch_end_ps": None,
        "previous_interval_ps": None,
        "previous_batch_size": None,
        "estimated_missing_samples": 0,
        "estimated_missing_batches": 0.0,
    }


def track_batch_gap(stats: dict, start_ps: int, interval_ps: int, sample_count: int) -> None:
    """Estimate missing samples between two received batches using timestamps."""
    stats["batch_count"] += 1

    previous_batch_end_ps = stats["previous_batch_end_ps"]
    previous_interval_ps = stats["previous_interval_ps"]
    previous_batch_size = stats["previous_batch_size"]

    if previous_batch_end_ps is not None:
        gap_ps = start_ps - previous_batch_end_ps
        reference_interval_ps = previous_interval_ps or interval_ps
        if reference_interval_ps and gap_ps > max(reference_interval_ps // 2, 1):
            missing_samples = int(round(gap_ps / reference_interval_ps))
            if missing_samples > 0:
                stats["estimated_missing_samples"] += missing_samples

                reference_batch_size = previous_batch_size or sample_count
                if reference_batch_size:
                    stats["estimated_missing_batches"] += missing_samples / reference_batch_size

    stats["previous_batch_end_ps"] = start_ps + max(sample_count, 0) * max(interval_ps, 0)
    stats["previous_interval_ps"] = interval_ps if interval_ps > 0 else previous_interval_ps
    stats["previous_batch_size"] = sample_count if sample_count > 0 else previous_batch_size


def empty_overflow_detail() -> dict:
    """Create an accumulator for firmware-reported overflow details."""
    return {
        "messages": 0,
        "dropped_batches": 0,
        "lost_samples": 0,
    }


def overflow_stream_name(message: str) -> str | None:
    """Map an overflow message to the host stream name."""
    lowered = message.lower()
    if "pin" in lowered:
        return "digital"
    if "adc" in lowered:
        return "analog"
    return None


def parse_overflow_details(message: str) -> dict[str, int]:
    """Extract structured key=value counts from a firmware overflow message."""
    details: dict[str, int] = {}
    for key, value in re.findall(r"([a-z_]+)=(\d+)", message.lower()):
        details[key] = int(value)
    return details


def print_capture_summary(
    mode: int,
    duration_s: float,
    output: str | None,
    pin_data: list[dict],
    adc_data: list[dict],
    pin_stats: dict,
    adc_stats: dict,
    overflow_details: dict[str, dict],
) -> None:
    """Print measured capture span and overflow estimates to stderr."""
    requested_duration_ps = seconds_to_picoseconds(duration_s)
    destination = output or "stdout"
    print(
        f"Capture complete: requested={format_duration_ps(requested_duration_ps)} output={destination}",
        file=sys.stderr,
    )

    if mode == MODE_HAT:
        print(
            f"Digital stream: samples={len(pin_data)} span={format_duration_ps(capture_entries_span_ps(pin_data))} "
            f"batches={pin_stats['batch_count']}",
            file=sys.stderr,
        )
    else:
        print(
            f"Analog stream: samples={len(adc_data)} span={format_duration_ps(capture_entries_span_ps(adc_data))} "
            f"batches={adc_stats['batch_count']}",
            file=sys.stderr,
        )
        if pin_data:
            print(
                f"Digital stream: samples={len(pin_data)} span={format_duration_ps(capture_entries_span_ps(pin_data))} "
                f"batches={pin_stats['batch_count']}",
                file=sys.stderr,
            )

    for stats in (pin_stats, adc_stats):
        sample_count = len(pin_data) if stats["name"] == "digital" else len(adc_data)
        actual_details = overflow_details.get(stats["name"], empty_overflow_detail())
        actual_messages = actual_details.get("messages", 0)
        actual_dropped_batches = actual_details.get("dropped_batches", 0)
        actual_lost_samples = actual_details.get("lost_samples", 0)
        estimated_missing_samples = stats["estimated_missing_samples"]
        estimated_missing_batches = stats["estimated_missing_batches"]
        if actual_messages or actual_lost_samples:
            total_samples = sample_count + actual_lost_samples
            coverage_loss = (actual_lost_samples / total_samples) if total_samples > 0 else 0.0
            details = [
                f"Overflow summary ({stats['name']}): messages={actual_messages}",
                f"dropped_batches={actual_dropped_batches}",
                f"lost_samples={actual_lost_samples}",
            ]
            if total_samples > 0:
                details.append(f"coverage_loss~={coverage_loss * 100:.2f}%")
            print(", ".join(details), file=sys.stderr)
            continue

        total_samples = sample_count + estimated_missing_samples
        coverage_loss = (estimated_missing_samples / total_samples) if total_samples > 0 else 0.0
        if estimated_missing_samples:
            details = [
                f"Overflow summary ({stats['name']}): estimated_missing_samples={estimated_missing_samples}",
            ]
            if estimated_missing_batches:
                details.append(f"estimated_dropped_batches~={estimated_missing_batches:.2f}")
            if total_samples > 0:
                details.append(f"estimated_coverage_loss~={coverage_loss * 100:.2f}%")
            print(", ".join(details), file=sys.stderr)


def handle_device_message(
    msg_type: int,
    payload: bytes,
    seen_messages: set[str],
    device_state: dict | None = None,
) -> bool:
    """Print device warnings and errors to stderr.

    Returns:
        True if the frame was consumed as a status or error message.
    """
    if msg_type == MSG_STATUS and payload and payload[0] == STATUS_OVERFLOW:
        key = "status:overflow"
        if device_state is not None:
            overflow_messages = device_state.setdefault("overflow_messages", [])
            overflow_messages.append("Capture overflow")
        if key not in seen_messages:
            print("Warning: device reported capture overflow", file=sys.stderr)
            seen_messages.add(key)
        return True

    if msg_type == MSG_ERROR:
        error_code = payload[0] if payload else 0
        message = payload[1:].decode("utf-8", errors="replace") if len(payload) > 1 else ""

        if error_code == STATUS_OVERFLOW:
            overflow_message = message or "Capture overflow"
            if device_state is not None:
                overflow_messages = device_state.setdefault("overflow_messages", [])
                overflow_messages.append(overflow_message)
                overflow_details = device_state.setdefault(
                    "overflow_details",
                    {
                        "digital": empty_overflow_detail(),
                        "analog": empty_overflow_detail(),
                    },
                )
                stream_name = overflow_stream_name(overflow_message)
                if stream_name is not None:
                    stream_details = overflow_details.setdefault(stream_name, empty_overflow_detail())
                    stream_details["messages"] += 1
                    parsed_details = parse_overflow_details(overflow_message)
                    stream_details["dropped_batches"] += parsed_details.get("dropped_batches", 0)
                    stream_details["lost_samples"] += parsed_details.get("lost_samples", 0)

            key = f"overflow:{overflow_message}"
            if key not in seen_messages:
                print(f"Warning: device reported capture overflow: {overflow_message}", file=sys.stderr)
                seen_messages.add(key)
            return True

        key = f"error:{error_code}:{message}"
        if key not in seen_messages:
            if message:
                print(f"Warning: device error {error_code}: {message}", file=sys.stderr)
            else:
                print(f"Warning: device error {error_code}", file=sys.stderr)
            seen_messages.add(key)
        return True

    return False


def format_protocol_event(event) -> str:
    """Format a decoded protocol event for text output."""
    timestamp_s = picoseconds_to_seconds(event.timestamp_ps)
    return f"{timestamp_s:.12f}s {event.summary}"


def require_port(args) -> str:
    """Return the configured serial port or exit with a usage error."""
    if args.port:
        return args.port

    print("Error: --port is required for this command", file=sys.stderr)
    sys.exit(2)


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
    port = require_port(args)
    reader = SerialReader(port)
    if not reader.connect():
        print(json.dumps({"status": "error", "message": "Connection failed"}))
        sys.exit(1)

    info = {
        "status": "connected",
        "port": port,
        "timestamp": datetime.now().isoformat(),
    }
    print(json.dumps(info))
    reader.disconnect()


def cmd_capture(args):
    """Capture data for a specified duration and save to CSV."""
    mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE
    duration = args.duration
    output = args.output
    port = require_port(args)

    reader = SerialReader(port)
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

    if mode == MODE_OSCILLOSCOPE:
        reader.configure_digital_enabled(args.digital == "on")

    if args.pin_divider != 1.0:
        if mode == MODE_HAT:
            if not reader.configure_hat_divider(args.pin_divider):
                print("Error: Failed to configure hat-mode digital divider", file=sys.stderr)
                reader.disconnect()
                sys.exit(1)
        elif not reader.configure_osc_digital_divider(args.pin_divider):
            print("Error: Failed to configure oscilloscope digital divider", file=sys.stderr)
            reader.disconnect()
            sys.exit(1)

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
    device_messages: set[str] = set()
    device_state: dict = {
        "overflow_messages": [],
        "overflow_details": {
            "digital": empty_overflow_detail(),
            "analog": empty_overflow_detail(),
        },
    }
    pin_stats = new_batch_stream_stats("digital")
    adc_stats = new_batch_stream_stats("analog")

    while running and (time.time() - start_time) < duration:
        result = reader.receive_frame(timeout=0.1)
        if result is None:
            continue

        msg_type, payload = result
        if handle_device_message(msg_type, payload, device_messages, device_state):
            continue

        timestamp = time.time() - start_time
        timestamp_ps = seconds_to_picoseconds(timestamp)

        if msg_type == MSG_PIN_DATA:
            snapshots = SerialReader.decode_pin_data(payload)
            for snap in snapshots:
                pin_data.append({
                    "index": sample_index,
                    "raw_sample_index": sample_index,
                    "timestamp": timestamp,
                    "timestamp_ps": timestamp_ps,
                    "gpio_raw": snap,
                })
                sample_index += 1

        elif msg_type == MSG_PIN_BATCH:
            batch = SerialReader.decode_pin_batch(payload)
            if batch is None:
                continue

            track_batch_gap(pin_stats, batch.start_time_ps, batch.sample_interval_ps, batch.sample_count)

            for offset, snap in enumerate(batch.snapshots):
                entry_timestamp_ps = (
                    batch.start_time_ps + offset * batch.sample_interval_ps
                )
                pin_data.append({
                    "index": sample_index,
                    "raw_sample_index": sample_index,
                    "timestamp": picoseconds_to_seconds(entry_timestamp_ps),
                    "timestamp_ps": entry_timestamp_ps,
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
                    "timestamp_ps": timestamp_ps,
                    "channel": ch,
                    "raw": val,
                    "voltage": SerialReader.adc_to_voltage(val),
                })
                sample_index += 1

        elif msg_type == MSG_ADC_BATCH:
            batch = SerialReader.decode_adc_batch(payload)
            if batch is None:
                continue

            track_batch_gap(adc_stats, batch.start_time_ps, batch.sample_interval_ps, batch.sample_count)

            for i, val in enumerate(batch.samples):
                ch = i % max(batch.channel_count, 1)
                entry_timestamp_ps = batch.start_time_ps + i * batch.sample_interval_ps
                adc_data.append({
                    "index": sample_index,
                    "timestamp": picoseconds_to_seconds(entry_timestamp_ps),
                    "timestamp_ps": entry_timestamp_ps,
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
        _write_capture_csv(output, mode, pin_data, adc_data, args.digital_export)
        print(f"Captured {sample_index} samples to {output}")
    else:
        # Write to stdout
        _write_capture_stdout(mode, pin_data, adc_data, args.digital_export)

    print_capture_summary(
        mode,
        duration_s=duration,
        output=output,
        pin_data=pin_data,
        adc_data=adc_data,
        pin_stats=pin_stats,
        adc_stats=adc_stats,
        overflow_details=device_state.get("overflow_details", {}),
    )


def _write_capture_csv(
    path: str,
    mode: int,
    pin_data: list,
    adc_data: list,
    digital_export: str = DIGITAL_EXPORT_FULL,
):
    """Write captured data to a CSV file."""
    with open(path, "w", newline="") as f:
        if mode == MODE_HAT:
            writer = csv.writer(f)
            if digital_export == DIGITAL_EXPORT_EDGE:
                entries = compress_pin_data(pin_data)
                header = [
                    "index",
                    "raw_sample_index",
                    "delta_samples",
                    "timestamp",
                    "timestamp_ps",
                    "delta_time_ps",
                    "gpio_raw",
                    "changed_mask",
                ]
            else:
                entries = pin_data
                header = ["index", "raw_sample_index", "timestamp", "timestamp_ps", "gpio_raw"]
            header.extend(f"GPIO{i}" for i in range(HAT_PIN_COUNT))
            writer.writerow(header)
            for entry in entries:
                timestamp_ps = entry_timestamp_ps(entry)
                timestamp_s = picoseconds_to_seconds(timestamp_ps)
                snap = entry["gpio_raw"]
                if digital_export == DIGITAL_EXPORT_EDGE:
                    row = [
                        entry["index"],
                        pin_entry_raw_sample_index(entry),
                        entry["delta_samples"],
                        f"{timestamp_s:.12f}",
                        timestamp_ps,
                        entry["delta_time_ps"],
                        f"0x{snap:08X}",
                        f"0x{entry['changed_mask']:08X}",
                    ]
                else:
                    row = [
                        entry["index"],
                        pin_entry_raw_sample_index(entry),
                        f"{timestamp_s:.12f}",
                        timestamp_ps,
                        f"0x{snap:08X}",
                    ]
                row.extend((snap >> i) & 1 for i in range(HAT_PIN_COUNT))
                writer.writerow(row)
        else:
            writer = csv.writer(f)
            writer.writerow(["index", "timestamp", "timestamp_ps", "channel", "raw", "voltage"])
            for entry in adc_data:
                timestamp_ps = entry_timestamp_ps(entry)
                timestamp_s = picoseconds_to_seconds(timestamp_ps)
                writer.writerow([
                    entry["index"],
                    f"{timestamp_s:.12f}",
                    timestamp_ps,
                    entry["channel"],
                    entry["raw"],
                    f"{entry['voltage']:.4f}",
                ])


def _write_capture_stdout(
    mode: int,
    pin_data: list,
    adc_data: list,
    digital_export: str = DIGITAL_EXPORT_FULL,
):
    """Write captured data to stdout in CSV format."""
    writer = csv.writer(sys.stdout)
    if mode == MODE_HAT:
        if digital_export == DIGITAL_EXPORT_EDGE:
            entries = compress_pin_data(pin_data)
            writer.writerow([
                "index",
                "raw_sample_index",
                "delta_samples",
                "timestamp",
                "timestamp_ps",
                "delta_time_ps",
                "gpio_raw",
                "changed_mask",
            ])
        else:
            entries = pin_data
            writer.writerow(["index", "raw_sample_index", "timestamp", "timestamp_ps", "gpio_raw"])

        for entry in entries:
            timestamp_ps = entry_timestamp_ps(entry)
            timestamp_s = picoseconds_to_seconds(timestamp_ps)
            if digital_export == DIGITAL_EXPORT_EDGE:
                writer.writerow([
                    entry["index"],
                    pin_entry_raw_sample_index(entry),
                    entry["delta_samples"],
                    f"{timestamp_s:.12f}",
                    timestamp_ps,
                    entry["delta_time_ps"],
                    f"0x{entry['gpio_raw']:08X}",
                    f"0x{entry['changed_mask']:08X}",
                ])
            else:
                writer.writerow([
                    entry["index"],
                    pin_entry_raw_sample_index(entry),
                    f"{timestamp_s:.12f}",
                    timestamp_ps,
                    f"0x{entry['gpio_raw']:08X}",
                ])
    else:
        writer.writerow(["index", "timestamp", "timestamp_ps", "channel", "raw", "voltage"])
        for entry in adc_data:
            timestamp_ps = entry_timestamp_ps(entry)
            timestamp_s = picoseconds_to_seconds(timestamp_ps)
            writer.writerow([
                entry["index"],
                f"{timestamp_s:.12f}",
                timestamp_ps,
                entry["channel"],
                entry["raw"],
                f"{entry['voltage']:.4f}",
            ])


def cmd_monitor(args):
    """Live monitoring mode — prints data to stdout continuously."""
    mode = MODE_HAT if args.mode == "hat" else MODE_OSCILLOSCOPE
    port = require_port(args)

    reader = SerialReader(port)
    if not reader.connect():
        print("Error: Connection failed", file=sys.stderr)
        sys.exit(1)

    if not reader.set_mode(mode):
        print("Error: Failed to set mode", file=sys.stderr)
        reader.disconnect()
        sys.exit(1)

    if mode == MODE_OSCILLOSCOPE:
        reader.configure_digital_enabled(args.digital == "on")

    if args.pin_divider != 1.0:
        if mode == MODE_HAT:
            if not reader.configure_hat_divider(args.pin_divider):
                print("Error: Failed to configure hat-mode digital divider", file=sys.stderr)
                reader.disconnect()
                sys.exit(1)
        elif not reader.configure_osc_digital_divider(args.pin_divider):
            print("Error: Failed to configure oscilloscope digital divider", file=sys.stderr)
            reader.disconnect()
            sys.exit(1)

    if not reader.start_sampling():
        print("Error: Failed to start sampling", file=sys.stderr)
        reader.disconnect()
        sys.exit(1)

    device_messages: set[str] = set()

    try:
        while running:
            result = reader.receive_frame(timeout=0.1)
            if result is None:
                continue

            msg_type, payload = result


            if handle_device_message(msg_type, payload, device_messages):
                continue

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

    elif msg_type == MSG_PIN_BATCH:
        batch = SerialReader.decode_pin_batch(payload)
        if batch is not None:
            obj = {
                "type": "pin_batch",
                "timestamp": ts,
                "start_time_ps": batch.start_time_ps,
                "sample_interval_ps": batch.sample_interval_ps,
                "sample_count": batch.sample_count,
                "pin_mask": batch.pin_mask,
                "snapshots": batch.snapshots,
            }
            print(json.dumps(obj), flush=True)

    elif msg_type == MSG_ADC_BATCH:
        batch = SerialReader.decode_adc_batch(payload)
        if batch is not None:
            obj = {
                "type": "adc_batch",
                "timestamp": ts,
                "start_time_ps": batch.start_time_ps,
                "sample_interval_ps": batch.sample_interval_ps,
                "sample_count": batch.sample_count,
                "channel_count": batch.channel_count,
                "samples": batch.samples,
            }
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

    elif msg_type == MSG_PIN_BATCH:
        batch = SerialReader.decode_pin_batch(payload)
        if batch is not None:
            start_s = batch.start_time_ps / 1_000_000_000_000.0
            print(
                f"PIN_BATCH count={batch.sample_count} start={start_s:.6f}s "
                f"interval_ps={batch.sample_interval_ps}",
                flush=True,
            )

    elif msg_type == MSG_ADC_BATCH:
        batch = SerialReader.decode_adc_batch(payload)
        if batch is not None:
            start_s = batch.start_time_ps / 1_000_000_000_000.0
            print(
                f"ADC_BATCH count={batch.sample_count} channels={batch.channel_count} "
                f"start={start_s:.6f}s interval_ps={batch.sample_interval_ps}",
                flush=True,
            )

    elif msg_type == MSG_TRIGGER:
        print("TRIGGER", flush=True)


def cmd_config(args):
    """Send configuration commands to the Pico."""
    port = require_port(args)
    reader = SerialReader(port)
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

    if args.digital is not None:
        if not reader.configure_digital_enabled(args.digital == "on"):
            success = False

    result = {"status": "ok" if success else "error"}
    print(json.dumps(result))
    reader.disconnect()


def cmd_protocol(args):
    """Decode protocol traffic from a digital capture CSV."""
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Error: Capture file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    diagnostics: list[str] = []

    try:
        capture = load_capture_csv(str(input_path))

        if args.decoder == "uart":
            if args.data_pin is None or args.baud is None:
                raise ValueError("UART decoding requires --data-pin and --baud")

            events = decode_uart(
                capture,
                data_pin=args.data_pin,
                baud=args.baud,
                data_bits=args.data_bits,
                parity=args.parity,
                stop_bits=args.stop_bits,
                invert=args.invert,
            )
        elif args.decoder == "i2c":
            if args.scl_pin is None or args.sda_pin is None:
                raise ValueError("I2C decoding requires --scl-pin and --sda-pin")

            events = decode_i2c(capture, scl_pin=args.scl_pin, sda_pin=args.sda_pin)
        elif args.decoder == "dshot":
            if args.data_pin is None:
                raise ValueError("DShot decoding requires --data-pin")

            events = decode_dshot(
                capture,
                data_pin=args.data_pin,
                dshot_rate=args.dshot_rate,
                bidirectional=args.bidirectional,
                pole_count=args.pole_count,
                diagnostics=diagnostics,
            )
        else:
            if args.clock_pin is None:
                raise ValueError("SPI decoding requires --clock-pin")
            if args.mosi_pin is None and args.miso_pin is None:
                raise ValueError("SPI decoding requires --mosi-pin and/or --miso-pin")

            events = decode_spi(
                capture,
                clock_pin=args.clock_pin,
                mosi_pin=args.mosi_pin,
                miso_pin=args.miso_pin,
                cs_pin=args.cs_pin,
                mode=args.spi_mode,
                bits_per_word=args.bits_per_word,
                bit_order=args.bit_order,
                cs_active=args.cs_active,
            )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.format == "json":
        for event in events:
            print(json.dumps(event.to_dict()), flush=True)
    else:
        for event in events:
            print(format_protocol_event(event), flush=True)

    if not events:
        for diagnostic in diagnostics:
            print(f"Diagnostic: {diagnostic}", file=sys.stderr)
        print("No protocol events decoded", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        prog="pico_oscilloscope",
        description="Pico Oscilloscope — CLI for capture and monitoring",
    )
    parser.add_argument("--port", "-p", help="Serial port (e.g., COM3, /dev/ttyACM0)")

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
    sub_capture.add_argument("--digital", choices=["on", "off"], default="on",
                             help="Enable or disable oscilloscope-mode digital capture")
    sub_capture.add_argument("--pin-divider", type=float, default=1.0,
                             help="Digital PIO clock divider (1.0 = fastest)")
    sub_capture.add_argument("--digital-export", choices=[DIGITAL_EXPORT_FULL, DIGITAL_EXPORT_EDGE],
                             default=DIGITAL_EXPORT_FULL,
                             help="Hat-mode digital export style")

    # monitor
    sub_monitor = subparsers.add_parser("monitor", help="Live monitoring (continuous)")
    sub_monitor.add_argument("--mode", "-m", choices=["hat", "oscilloscope"], default="hat",
                             help="Operating mode")
    sub_monitor.add_argument("--format", "-f", choices=["text", "json"], default="text",
                             help="Output format")
    sub_monitor.add_argument("--digital", choices=["on", "off"], default="on",
                             help="Enable or disable oscilloscope-mode digital capture")
    sub_monitor.add_argument("--pin-divider", type=float, default=1.0,
                             help="Digital PIO clock divider (1.0 = fastest)")

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
    sub_config.add_argument("--digital", choices=["on", "off"],
                            help="Enable or disable oscilloscope-mode digital capture")

    # protocol
    sub_protocol = subparsers.add_parser(
        "protocol",
        help="Decode UART, I2C, SPI, or DShot traffic from a digital capture CSV",
    )
    sub_protocol.add_argument("--input", "-i", required=True,
                              help="Digital capture CSV file")
    sub_protocol.add_argument("decoder", choices=["uart", "i2c", "spi", "dshot"],
                              help="Protocol decoder to run")
    sub_protocol.add_argument("--format", "-f", choices=["text", "json"], default="text",
                              help="Output format")
    sub_protocol.add_argument("--data-pin", type=int,
                              help="UART RX/TX GPIO pin")
    sub_protocol.add_argument("--baud", type=float,
                              help="UART baud rate")
    sub_protocol.add_argument("--data-bits", type=int, default=8,
                              help="UART data bits (5-9)")
    sub_protocol.add_argument("--parity", choices=["none", "even", "odd"], default="none",
                              help="UART parity")
    sub_protocol.add_argument("--stop-bits", type=int, choices=[1, 2], default=1,
                              help="UART stop bits")
    sub_protocol.add_argument("--invert", action="store_true",
                              help="Invert UART line polarity before decoding")
    sub_protocol.add_argument("--dshot-rate", choices=["auto", "150", "300", "600"],
                              default="auto",
                              help="DShot bitrate in kbit/s")
    sub_protocol.add_argument("--bidirectional", action="store_true",
                              help="Decode shared-line bidirectional DShot telemetry and EDT")
    sub_protocol.add_argument("--pole-count", type=int,
                              help="Motor pole count used to convert electrical RPM to mechanical RPM")
    sub_protocol.add_argument("--scl-pin", type=int,
                              help="I2C SCL GPIO pin")
    sub_protocol.add_argument("--sda-pin", type=int,
                              help="I2C SDA GPIO pin")
    sub_protocol.add_argument("--clock-pin", type=int,
                              help="SPI clock GPIO pin")
    sub_protocol.add_argument("--mosi-pin", type=int,
                              help="SPI MOSI GPIO pin")
    sub_protocol.add_argument("--miso-pin", type=int,
                              help="SPI MISO GPIO pin")
    sub_protocol.add_argument("--cs-pin", type=int,
                              help="SPI chip-select GPIO pin")
    sub_protocol.add_argument("--spi-mode", type=int, choices=[0, 1, 2, 3], default=0,
                              help="SPI mode")
    sub_protocol.add_argument("--bits-per-word", type=int, default=8,
                              help="SPI bits per word")
    sub_protocol.add_argument("--bit-order", choices=["msb", "lsb"], default="msb",
                              help="SPI bit order")
    sub_protocol.add_argument("--cs-active", choices=["low", "high"], default="low",
                              help="SPI chip-select active polarity")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "capture": cmd_capture,
        "monitor": cmd_monitor,
        "config": cmd_config,
        "protocol": cmd_protocol,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
