"""Protocol analyzer helpers for Pico Oscilloscope digital captures."""

from __future__ import annotations

from bisect import bisect_right
import csv
from dataclasses import dataclass
from typing import Any, Optional

TIME_SCALE_PS = 1_000_000_000_000
DSHOT_SUPPORTED_RATES = (150, 300, 600)
DSHOT_RATE_PERIOD_PS = {
    rate: int(round(TIME_SCALE_PS / (rate * 1000))) for rate in DSHOT_SUPPORTED_RATES
}
DSHOT_PULSE_ZERO_RATIO = 0.375
DSHOT_PULSE_ONE_RATIO = 0.75
DSHOT_PULSE_RATIO_TOLERANCE = 0.18
DSHOT_INTERVAL_RATIO_TOLERANCE = 0.25
DSHOT_REPLY_DELAY_MIN_PS = 20_000_000
DSHOT_REPLY_DELAY_MAX_PS = 45_000_000
DSHOT_REPLY_DELAY_TARGET_PS = 30_000_000
DSHOT_REPLY_BITS = 21
DSHOT_GCR_SYMBOLS = {
    0x0: 0x19,
    0x1: 0x1B,
    0x2: 0x12,
    0x3: 0x13,
    0x4: 0x1D,
    0x5: 0x15,
    0x6: 0x16,
    0x7: 0x17,
    0x8: 0x1A,
    0x9: 0x09,
    0xA: 0x0A,
    0xB: 0x0B,
    0xC: 0x1E,
    0xD: 0x0D,
    0xE: 0x0E,
    0xF: 0x0F,
}
DSHOT_GCR_DECODE = {value: key for key, value in DSHOT_GCR_SYMBOLS.items()}
DSHOT_COMMAND_NAMES = {
    0: "MOTOR_STOP",
    1: "BEEP1",
    2: "BEEP2",
    3: "BEEP3",
    4: "BEEP4",
    5: "BEEP5",
    6: "ESC_INFO",
    7: "SPIN_DIRECTION_1",
    8: "SPIN_DIRECTION_2",
    9: "3D_MODE_OFF",
    10: "3D_MODE_ON",
    12: "SAVE_SETTINGS",
    13: "EXTENDED_TELEMETRY_ENABLE",
    14: "EXTENDED_TELEMETRY_DISABLE",
    20: "SPIN_DIRECTION_NORMAL",
    21: "SPIN_DIRECTION_REVERSED",
    22: "LED0_ON",
    23: "LED1_ON",
    24: "LED2_ON",
    25: "LED3_ON",
    26: "LED0_OFF",
    27: "LED1_OFF",
    28: "LED2_OFF",
    29: "LED3_OFF",
    32: "SIGNAL_LINE_TELEMETRY_DISABLE",
    33: "SIGNAL_LINE_TELEMETRY_ENABLE",
    34: "CONTINUOUS_ERPM_TELEMETRY",
    35: "CONTINUOUS_ERPM_PERIOD_TELEMETRY",
    42: "SIGNAL_LINE_TEMPERATURE_TELEMETRY",
    43: "SIGNAL_LINE_VOLTAGE_TELEMETRY",
    44: "SIGNAL_LINE_CURRENT_TELEMETRY",
    45: "SIGNAL_LINE_CONSUMPTION_TELEMETRY",
    46: "SIGNAL_LINE_ERPM_TELEMETRY",
    47: "SIGNAL_LINE_ERPM_PERIOD_TELEMETRY",
}


@dataclass(slots=True)
class PinSegment:
    """Stable pin level between two observed transitions."""

    level: int
    start_ps: int
    end_ps: int
    start_sample_index: int
    end_sample_index: int


@dataclass(slots=True)
class DShotFrame:
    """Decoded forward DShot frame."""

    rate: int
    bit_period_ps: int
    start_ps: int
    end_ps: int
    start_sample_index: int
    end_sample_index: int
    word: int
    value: int
    telemetry_request: bool
    checksum_variant: str
    shared_line: bool
    quality: float


@dataclass(slots=True)
class DigitalCapture:
    """Digital capture loaded from a CSV export."""

    timestamps_ps: list[int]
    snapshots: list[int]
    pin_count: int
    sample_indexes: list[int]


@dataclass(slots=True)
class ProtocolEvent:
    """Decoded protocol event."""

    timestamp_ps: int
    protocol: str
    summary: str
    fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly dictionary."""
        return {
            "timestamp": self.timestamp_ps / TIME_SCALE_PS,
            "timestamp_ps": self.timestamp_ps,
            "protocol": self.protocol,
            "summary": self.summary,
            **self.fields,
        }


def load_capture_csv(path: str) -> DigitalCapture:
    """Load a digital capture CSV exported by the CLI.

    Supports both full per-sample exports and edge-compressed exports.
    """
    timestamps_ps: list[int] = []
    snapshots: list[int] = []
    sample_indexes: list[int] = []

    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        gpio_fields = [field for field in fieldnames if field.startswith("GPIO")]

        if not gpio_fields and "gpio_raw" not in fieldnames:
            raise ValueError("Capture does not contain digital GPIO columns")

        for row_index, row in enumerate(reader):
            timestamps_ps.append(_row_timestamp_ps(row))
            snapshots.append(_row_snapshot(row, gpio_fields))
            sample_indexes.append(_row_sample_index(row, row_index))

    if not timestamps_ps:
        raise ValueError("Capture is empty")

    if gpio_fields:
        pin_count = max(int(field[4:]) for field in gpio_fields) + 1
    else:
        pin_count = 30

    return DigitalCapture(
        timestamps_ps=timestamps_ps,
        snapshots=snapshots,
        pin_count=pin_count,
        sample_indexes=sample_indexes,
    )


def decode_uart(
    capture: DigitalCapture,
    data_pin: int,
    baud: float,
    data_bits: int = 8,
    parity: str = "none",
    stop_bits: int = 1,
    invert: bool = False,
) -> list[ProtocolEvent]:
    """Decode an asynchronous UART stream from a digital capture."""
    _validate_pin(data_pin)

    if baud <= 0:
        raise ValueError("UART baud must be greater than zero")
    if data_bits < 5 or data_bits > 9:
        raise ValueError("UART data bits must be between 5 and 9")
    if parity not in {"none", "even", "odd"}:
        raise ValueError("UART parity must be none, even, or odd")
    if stop_bits not in {1, 2}:
        raise ValueError("UART stop bits must be 1 or 2")

    bit_period_ps = int(round(TIME_SCALE_PS / baud))
    idle_state = 0 if invert else 1
    start_state = 1 - idle_state
    events: list[ProtocolEvent] = []
    index = 1

    while index < len(capture.snapshots):
        previous_state = _snapshot_pin(capture.snapshots[index - 1], data_pin)
        current_state = _snapshot_pin(capture.snapshots[index], data_pin)

        if previous_state == idle_state and current_state == start_state:
            frame_start_ps = capture.timestamps_ps[index]
            bits: list[int] = []

            for bit_index in range(data_bits):
                sample_time_ps = frame_start_ps + ((3 + (bit_index * 2)) * bit_period_ps) // 2
                bit_value = _sample_pin_at(capture, data_pin, sample_time_ps)
                bits.append(bit_value ^ int(invert))

            parity_value: Optional[int] = None
            parity_ok: Optional[bool] = None
            parity_bits = 0

            if parity != "none":
                parity_bits = 1
                parity_time_ps = frame_start_ps + ((3 + (data_bits * 2)) * bit_period_ps) // 2
                parity_value = _sample_pin_at(capture, data_pin, parity_time_ps) ^ int(invert)
                expected = sum(bits) & 1
                if parity == "odd":
                    expected ^= 1
                parity_ok = parity_value == expected

            stop_ok = True
            stop_base = data_bits + parity_bits
            for stop_index in range(stop_bits):
                stop_time_ps = frame_start_ps + ((3 + ((stop_base + stop_index) * 2)) * bit_period_ps) // 2
                stop_state = _sample_pin_at(capture, data_pin, stop_time_ps) ^ int(invert)
                if stop_state != 1:
                    stop_ok = False

            value = _bits_to_int(bits, bit_order="lsb")
            hex_width = max(2, (data_bits + 3) // 4)
            summary = f"UART GPIO{data_pin} 0x{value:0{hex_width}X}"
            ascii_text = _uart_ascii(value)
            if ascii_text is not None:
                summary += f" '{ascii_text}'"
            if not stop_ok:
                summary += " FRAME_ERROR"
            elif parity_ok is False:
                summary += " PARITY_ERROR"

            fields: dict[str, Any] = {
                "pin": data_pin,
                "baud": baud,
                "data_bits": data_bits,
                "parity": parity,
                "stop_bits": stop_bits,
                "invert": invert,
                "value": value,
                "hex": f"0x{value:0{hex_width}X}",
                "bits": bits,
                "frame_error": not stop_ok,
            }

            if ascii_text is not None:
                fields["ascii"] = ascii_text
            if parity_value is not None:
                fields["parity_value"] = parity_value
                fields["parity_ok"] = parity_ok

            events.append(
                ProtocolEvent(
                    timestamp_ps=frame_start_ps,
                    protocol="uart",
                    summary=summary,
                    fields=fields,
                )
            )

            frame_end_ps = frame_start_ps + ((1 + data_bits + parity_bits + stop_bits) * bit_period_ps)
            while index < len(capture.timestamps_ps) and capture.timestamps_ps[index] <= frame_end_ps:
                index += 1
            continue

        index += 1

    return events


def decode_i2c(capture: DigitalCapture, scl_pin: int, sda_pin: int) -> list[ProtocolEvent]:
    """Decode an I2C bus from a digital capture."""
    _validate_pin(scl_pin)
    _validate_pin(sda_pin)

    events: list[ProtocolEvent] = []
    in_frame = False
    current_bits: list[int] = []
    byte_index = 0

    for index in range(1, len(capture.snapshots)):
        previous = capture.snapshots[index - 1]
        current = capture.snapshots[index]
        timestamp_ps = capture.timestamps_ps[index]
        prev_scl = _snapshot_pin(previous, scl_pin)
        curr_scl = _snapshot_pin(current, scl_pin)
        prev_sda = _snapshot_pin(previous, sda_pin)
        curr_sda = _snapshot_pin(current, sda_pin)

        if prev_sda == 1 and curr_sda == 0 and curr_scl == 1:
            event_name = "restart" if in_frame else "start"
            events.append(
                ProtocolEvent(
                    timestamp_ps=timestamp_ps,
                    protocol="i2c",
                    summary=event_name.upper(),
                    fields={
                        "event": event_name,
                        "scl_pin": scl_pin,
                        "sda_pin": sda_pin,
                    },
                )
            )
            in_frame = True
            current_bits.clear()
            byte_index = 0
            continue

        if not in_frame:
            continue

        if prev_sda == 0 and curr_sda == 1 and curr_scl == 1:
            events.append(
                ProtocolEvent(
                    timestamp_ps=timestamp_ps,
                    protocol="i2c",
                    summary="STOP",
                    fields={
                        "event": "stop",
                        "scl_pin": scl_pin,
                        "sda_pin": sda_pin,
                    },
                )
            )
            in_frame = False
            current_bits.clear()
            continue

        if prev_scl == 0 and curr_scl == 1:
            current_bits.append(curr_sda)

            if len(current_bits) == 9:
                byte_value = _bits_to_int(current_bits[:8], bit_order="msb")
                ack = current_bits[8] == 0

                fields: dict[str, Any] = {
                    "byte_index": byte_index,
                    "value": byte_value,
                    "hex": f"0x{byte_value:02X}",
                    "ack": ack,
                    "scl_pin": scl_pin,
                    "sda_pin": sda_pin,
                }

                if byte_index == 0:
                    address = byte_value >> 1
                    read = bool(byte_value & 1)
                    fields["address"] = address
                    fields["read"] = read
                    summary = f"ADDR 0x{address:02X} {'R' if read else 'W'} {'ACK' if ack else 'NACK'}"
                else:
                    summary = f"DATA 0x{byte_value:02X} {'ACK' if ack else 'NACK'}"

                events.append(
                    ProtocolEvent(
                        timestamp_ps=timestamp_ps,
                        protocol="i2c",
                        summary=summary,
                        fields=fields,
                    )
                )

                current_bits.clear()
                byte_index += 1

    return events


def decode_spi(
    capture: DigitalCapture,
    clock_pin: int,
    mosi_pin: Optional[int] = None,
    miso_pin: Optional[int] = None,
    cs_pin: Optional[int] = None,
    mode: int = 0,
    bits_per_word: int = 8,
    bit_order: str = "msb",
    cs_active: str = "low",
) -> list[ProtocolEvent]:
    """Decode an SPI bus from a digital capture."""
    _validate_pin(clock_pin)
    if mosi_pin is None and miso_pin is None:
        raise ValueError("At least one of MOSI or MISO pins must be provided")
    if mosi_pin is not None:
        _validate_pin(mosi_pin)
    if miso_pin is not None:
        _validate_pin(miso_pin)
    if cs_pin is not None:
        _validate_pin(cs_pin)
    if mode not in {0, 1, 2, 3}:
        raise ValueError("SPI mode must be 0, 1, 2, or 3")
    if bits_per_word <= 0:
        raise ValueError("SPI bits per word must be greater than zero")
    if bit_order not in {"msb", "lsb"}:
        raise ValueError("SPI bit order must be msb or lsb")
    if cs_active not in {"low", "high"}:
        raise ValueError("SPI chip-select polarity must be low or high")

    cpol = 1 if mode in {2, 3} else 0
    cpha = 1 if mode in {1, 3} else 0
    cs_active_level = 0 if cs_active == "low" else 1
    events: list[ProtocolEvent] = []
    mosi_bits: list[int] = []
    miso_bits: list[int] = []
    word_start_ps: Optional[int] = None
    word_index = 0
    cs_window_index = 0 if cs_pin is None else -1
    cs_window_started_active = False

    def start_cs_window(timestamp_ps: int, partial_start: bool) -> None:
        nonlocal cs_window_index, cs_window_started_active, word_index, word_start_ps

        if cs_pin is not None:
            cs_window_index += 1

        cs_window_started_active = partial_start
        mosi_bits.clear()
        miso_bits.clear()
        word_start_ps = None
        word_index = 0

        if partial_start:
            events.append(
                ProtocolEvent(
                    timestamp_ps=timestamp_ps,
                    protocol="spi",
                    summary="CS_WINDOW capture started while CS was asserted; first frame may be partial",
                    fields={
                        "kind": "cs_window",
                        "clock_pin": clock_pin,
                        "mode": mode,
                        "bits_per_word": bits_per_word,
                        "bit_order": bit_order,
                        "cs_pin": cs_pin,
                        "cs_active": cs_active,
                        "cs_window_index": cs_window_index,
                        "partial_start": True,
                    },
                )
            )

    def emit_partial_frame(timestamp_ps: int, reason: str) -> None:
        nonlocal word_start_ps

        bit_count = len(mosi_bits) if mosi_pin is not None else len(miso_bits)
        if bit_count == 0:
            return

        fields: dict[str, Any] = {
            "kind": "partial_frame",
            "partial": True,
            "reason": reason,
            "clock_pin": clock_pin,
            "mode": mode,
            "bits_per_word": bits_per_word,
            "bit_order": bit_order,
            "bits_captured": bit_count,
        }
        summary_parts = [f"PARTIAL {bit_count}/{bits_per_word} bits", reason]

        if cs_pin is not None:
            fields["cs_pin"] = cs_pin
            fields["cs_active"] = cs_active
            fields["cs_window_index"] = cs_window_index

        if mosi_pin is not None:
            mosi_value = _bits_to_int(mosi_bits, bit_order=bit_order)
            fields["mosi_pin"] = mosi_pin
            fields["mosi"] = mosi_value
            fields["mosi_hex"] = f"0x{mosi_value:0{max(2, (bit_count + 3) // 4)}X}"
            fields["mosi_bits"] = mosi_bits.copy()
            summary_parts.append(f"MOSI={fields['mosi_hex']}")

        if miso_pin is not None:
            miso_value = _bits_to_int(miso_bits, bit_order=bit_order)
            fields["miso_pin"] = miso_pin
            fields["miso"] = miso_value
            fields["miso_hex"] = f"0x{miso_value:0{max(2, (bit_count + 3) // 4)}X}"
            fields["miso_bits"] = miso_bits.copy()
            summary_parts.append(f"MISO={fields['miso_hex']}")

        events.append(
            ProtocolEvent(
                timestamp_ps=word_start_ps or timestamp_ps,
                protocol="spi",
                summary=" ".join(summary_parts),
                fields=fields,
            )
        )

        mosi_bits.clear()
        miso_bits.clear()
        word_start_ps = None

    if cs_pin is not None:
        if _cs_active(capture.snapshots[0], cs_pin, cs_active_level):
            start_cs_window(capture.timestamps_ps[0], partial_start=True)
    else:
        cs_window_started_active = False

    for index in range(1, len(capture.snapshots)):
        previous = capture.snapshots[index - 1]
        current = capture.snapshots[index]
        timestamp_ps = capture.timestamps_ps[index]

        previous_active = _cs_active(previous, cs_pin, cs_active_level)
        current_active = _cs_active(current, cs_pin, cs_active_level)

        if cs_pin is not None and not previous_active and current_active:
            start_cs_window(timestamp_ps, partial_start=False)
            continue

        if previous_active and not current_active:
            emit_partial_frame(timestamp_ps, "before CS deassert")
            mosi_bits.clear()
            miso_bits.clear()
            word_start_ps = None
            cs_window_started_active = False
            word_index = 0
            continue

        if not current_active:
            continue

        prev_clk = _snapshot_pin(previous, clock_pin)
        curr_clk = _snapshot_pin(current, clock_pin)

        if not _spi_sample_edge(prev_clk, curr_clk, cpol, cpha):
            continue

        if word_start_ps is None:
            word_start_ps = timestamp_ps

        if mosi_pin is not None:
            mosi_bits.append(_snapshot_pin(current, mosi_pin))
        if miso_pin is not None:
            miso_bits.append(_snapshot_pin(current, miso_pin))

        bit_count = len(mosi_bits) if mosi_pin is not None else len(miso_bits)
        if bit_count < bits_per_word:
            continue

        fields: dict[str, Any] = {
            "clock_pin": clock_pin,
            "mode": mode,
            "bits_per_word": bits_per_word,
            "bit_order": bit_order,
            "word_index": word_index,
        }
        summary_parts: list[str] = []

        if cs_pin is not None:
            fields["cs_pin"] = cs_pin
            fields["cs_active"] = cs_active
            fields["cs_window_index"] = cs_window_index
            fields["partial_window_start"] = cs_window_started_active

        if mosi_pin is not None:
            mosi_value = _bits_to_int(mosi_bits, bit_order=bit_order)
            fields["mosi"] = mosi_value
            fields["mosi_hex"] = f"0x{mosi_value:0{max(2, (bits_per_word + 3) // 4)}X}"
            fields["mosi_pin"] = mosi_pin
            summary_parts.append(f"MOSI={fields['mosi_hex']}")

        if miso_pin is not None:
            miso_value = _bits_to_int(miso_bits, bit_order=bit_order)
            fields["miso"] = miso_value
            fields["miso_hex"] = f"0x{miso_value:0{max(2, (bits_per_word + 3) // 4)}X}"
            fields["miso_pin"] = miso_pin
            summary_parts.append(f"MISO={fields['miso_hex']}")

        if cs_window_started_active:
            summary_parts.append("PARTIAL_WINDOW_START")

        events.append(
            ProtocolEvent(
                timestamp_ps=word_start_ps,
                protocol="spi",
                summary=" ".join(summary_parts),
                fields=fields,
            )
        )

        mosi_bits.clear()
        miso_bits.clear()
        word_start_ps = None
        word_index += 1

    emit_partial_frame(capture.timestamps_ps[-1], "at capture end")

    return events


def decode_dshot(
    capture: DigitalCapture,
    data_pin: int,
    dshot_rate: str | int = "auto",
    bidirectional: bool = False,
    pole_count: Optional[int] = None,
    diagnostics: Optional[list[str]] = None,
) -> list[ProtocolEvent]:
    """Decode DShot forward frames and shared-line telemetry."""
    _validate_pin(data_pin)

    if pole_count is not None and pole_count <= 0:
        raise ValueError("DShot pole count must be greater than zero")

    segments = _build_pin_segments(capture, data_pin)
    if not segments:
        if diagnostics is not None:
            diagnostics.append("No captured pin segments were available for DShot analysis")
        return []

    candidate_rates = _normalize_dshot_rates(dshot_rate)
    shared_line = bool(bidirectional)
    best_rate: Optional[int] = None
    best_frames: list[DShotFrame] = []

    for rate in candidate_rates:
        frames = _scan_dshot_frames(segments, rate, shared_line)
        if _prefer_dshot_frames(frames, rate, best_frames, best_rate):
            best_rate = rate
            best_frames = frames

    if not best_frames and diagnostics is not None:
        diagnostics.extend(_diagnose_dshot_failure(capture, segments, candidate_rates, shared_line))

    events: list[ProtocolEvent] = []
    for frame in best_frames:
        events.append(_build_dshot_forward_event(data_pin, frame))
        if shared_line:
            reply_event = _decode_dshot_reply(
                capture,
                data_pin=data_pin,
                frame=frame,
                pole_count=pole_count,
            )
            if reply_event is not None:
                events.append(reply_event)

    events.sort(key=lambda event: (event.timestamp_ps, 0 if event.protocol == "dshot" else 1))
    return events


def _row_timestamp_ps(row: dict[str, str]) -> int:
    timestamp_ps = (row.get("timestamp_ps") or "").strip()
    if timestamp_ps:
        return int(timestamp_ps)

    timestamp = (row.get("timestamp") or "").strip()
    if not timestamp:
        raise ValueError("Capture row is missing timestamp information")

    return int(round(float(timestamp) * TIME_SCALE_PS))


def _row_snapshot(row: dict[str, str], gpio_fields: list[str]) -> int:
    gpio_raw = (row.get("gpio_raw") or "").strip()
    if gpio_raw:
        return int(gpio_raw, 0)

    snapshot = 0
    for field in gpio_fields:
        value = (row.get(field) or "").strip()
        if value and int(value):
            snapshot |= 1 << int(field[4:])
    return snapshot


def _row_sample_index(row: dict[str, str], fallback: int) -> int:
    for key in ("raw_sample_index", "sample_index", "index"):
        value = (row.get(key) or "").strip()
        if value:
            return int(value)
    return fallback


def _build_pin_segments(capture: DigitalCapture, pin: int) -> list[PinSegment]:
    segments: list[PinSegment] = []
    current_level = _snapshot_pin(capture.snapshots[0], pin)
    start_ps = capture.timestamps_ps[0]
    start_sample_index = capture.sample_indexes[0]

    for index in range(1, len(capture.snapshots)):
        next_level = _snapshot_pin(capture.snapshots[index], pin)
        if next_level == current_level:
            continue

        transition_time_ps = capture.timestamps_ps[index]
        transition_sample_index = capture.sample_indexes[index]
        if transition_time_ps > start_ps:
            segments.append(
                PinSegment(
                    level=current_level,
                    start_ps=start_ps,
                    end_ps=transition_time_ps,
                    start_sample_index=start_sample_index,
                    end_sample_index=transition_sample_index,
                )
            )

        current_level = next_level
        start_ps = transition_time_ps
        start_sample_index = transition_sample_index

    segments.append(
        PinSegment(
            level=current_level,
            start_ps=start_ps,
            end_ps=capture.timestamps_ps[-1],
            start_sample_index=start_sample_index,
            end_sample_index=capture.sample_indexes[-1],
        )
    )
    return segments


def _normalize_dshot_rates(dshot_rate: str | int) -> list[int]:
    if dshot_rate == "auto":
        return list(DSHOT_SUPPORTED_RATES)

    rate = int(dshot_rate)
    if rate not in DSHOT_SUPPORTED_RATES:
        supported = ", ".join(str(item) for item in DSHOT_SUPPORTED_RATES)
        raise ValueError(f"DShot rate must be one of: auto, {supported}")

    return [rate]


def _diagnose_dshot_failure(
    capture: DigitalCapture,
    segments: list[PinSegment],
    candidate_rates: list[int],
    shared_line: bool,
) -> list[str]:
    diagnostics: list[str] = []
    capture_span_ps = _capture_span_ps(capture)
    minimum_frame_ps = min(16 * DSHOT_RATE_PERIOD_PS[rate] for rate in candidate_rates)
    active_level = 0 if shared_line else 1
    pulse_count = sum(
        1 for segment in segments
        if segment.level == active_level and segment.end_ps > segment.start_ps
    )

    if capture_span_ps < minimum_frame_ps:
        if len(candidate_rates) == 1:
            rate = candidate_rates[0]
            minimum_frame_ps = 16 * DSHOT_RATE_PERIOD_PS[rate]
            diagnostics.append(
                f"{_dshot_rate_label(rate)} capture span too short: captured {_format_capture_duration(capture_span_ps)}, "
                f"need at least {_format_capture_duration(minimum_frame_ps)} for one full frame"
            )
        else:
            fastest_rate = max(candidate_rates)
            diagnostics.append(
                f"Capture span too short: captured {_format_capture_duration(capture_span_ps)}, "
                f"need at least {_format_capture_duration(minimum_frame_ps)} for one full {_dshot_rate_label(fastest_rate)} frame"
            )
        return diagnostics

    if 0 < pulse_count < 16:
        diagnostics.append(
            f"Frame incomplete: captured {pulse_count} active pulses, need 16 for a complete DShot frame"
        )
        return diagnostics

    if pulse_count == 0:
        diagnostics.append("No DShot-like pulse train was observed on the selected pin")
        return diagnostics

    rate_list = ", ".join(_dshot_rate_label(rate) for rate in candidate_rates)
    diagnostics.append(
        f"Observed transitions on the selected pin, but no valid timing matched {rate_list}"
    )
    return diagnostics


def _capture_span_ps(capture: DigitalCapture) -> int:
    if len(capture.timestamps_ps) < 2:
        return 0
    return max(0, capture.timestamps_ps[-1] - capture.timestamps_ps[0])


def _format_capture_duration(duration_ps: int) -> str:
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


def _prefer_dshot_frames(
    candidate_frames: list[DShotFrame],
    candidate_rate: int,
    current_frames: list[DShotFrame],
    current_rate: Optional[int],
) -> bool:
    if len(candidate_frames) != len(current_frames):
        return len(candidate_frames) > len(current_frames)

    if not candidate_frames:
        return current_rate is None or candidate_rate > current_rate

    candidate_quality = sum(frame.quality for frame in candidate_frames) / len(candidate_frames)
    current_quality = sum(frame.quality for frame in current_frames) / len(current_frames)
    if abs(candidate_quality - current_quality) > 1e-9:
        return candidate_quality < current_quality

    return current_rate is None or candidate_rate > current_rate


def _scan_dshot_frames(segments: list[PinSegment], rate: int, shared_line: bool) -> list[DShotFrame]:
    active_level = 0 if shared_line else 1
    pulses = [segment for segment in segments if segment.level == active_level and segment.end_ps > segment.start_ps]
    frames: list[DShotFrame] = []
    pulse_index = 0

    while pulse_index <= len(pulses) - 16:
        candidate = _decode_dshot_frame_window(
            pulses[pulse_index:pulse_index + 16],
            rate=rate,
            shared_line=shared_line,
        )
        if candidate is None:
            pulse_index += 1
            continue

        frames.append(candidate)
        pulse_index += 16

    return frames


def _decode_dshot_frame_window(
    pulses: list[PinSegment],
    rate: int,
    shared_line: bool,
) -> Optional[DShotFrame]:
    bit_period_ps = DSHOT_RATE_PERIOD_PS[rate]
    bits: list[int] = []
    quality = 0.0

    for pulse in pulses:
        classified = _classify_dshot_pulse(pulse.end_ps - pulse.start_ps, bit_period_ps)
        if classified is None:
            return None

        bit_value, error = classified
        bits.append(bit_value)
        quality += error

    for index in range(len(pulses) - 1):
        interval_ps = pulses[index + 1].start_ps - pulses[index].start_ps
        interval_ratio = interval_ps / bit_period_ps
        interval_error = abs(interval_ratio - 1.0)
        if interval_error > DSHOT_INTERVAL_RATIO_TOLERANCE:
            return None
        quality += interval_error

    word = _bits_to_int(bits, bit_order="msb")
    data12 = word >> 4
    checksum = word & 0x0F
    expected_checksum = _dshot_checksum(data12)
    checksum_variant = "normal"

    if checksum != expected_checksum:
        inverted_checksum = (~expected_checksum) & 0x0F
        if not shared_line or checksum != inverted_checksum:
            return None
        checksum_variant = "inverted"

    return DShotFrame(
        rate=rate,
        bit_period_ps=bit_period_ps,
        start_ps=pulses[0].start_ps,
        end_ps=pulses[-1].end_ps,
        start_sample_index=pulses[0].start_sample_index,
        end_sample_index=pulses[-1].end_sample_index,
        word=word,
        value=word >> 5,
        telemetry_request=bool((word >> 4) & 0x01),
        checksum_variant=checksum_variant,
        shared_line=shared_line,
        quality=quality,
    )


def _classify_dshot_pulse(pulse_duration_ps: int, bit_period_ps: int) -> Optional[tuple[int, float]]:
    if pulse_duration_ps <= 0 or bit_period_ps <= 0:
        return None

    ratio = pulse_duration_ps / bit_period_ps
    zero_error = abs(ratio - DSHOT_PULSE_ZERO_RATIO)
    one_error = abs(ratio - DSHOT_PULSE_ONE_RATIO)

    if zero_error > DSHOT_PULSE_RATIO_TOLERANCE and one_error > DSHOT_PULSE_RATIO_TOLERANCE:
        return None

    if zero_error <= one_error:
        return 0, zero_error
    return 1, one_error


def _dshot_checksum(data12: int) -> int:
    return (data12 ^ (data12 >> 4) ^ (data12 >> 8)) & 0x0F


def _build_dshot_forward_event(data_pin: int, frame: DShotFrame) -> ProtocolEvent:
    rate_label = _dshot_rate_label(frame.rate)
    fields: dict[str, Any] = {
        "pin": data_pin,
        "rate": frame.rate,
        "shared_line": frame.shared_line,
        "telemetry_request": frame.telemetry_request,
        "checksum_variant": frame.checksum_variant,
        "word": f"0x{frame.word:04X}",
        "sample_index": frame.start_sample_index,
        "frame_end_sample_index": frame.end_sample_index,
    }

    if frame.value == 0:
        summary = f"{rate_label} MOTOR_STOP"
        fields["kind"] = "motor_stop"
    elif frame.value <= 47:
        command_name = DSHOT_COMMAND_NAMES.get(frame.value, f"COMMAND_{frame.value}")
        summary = f"{rate_label} CMD {frame.value} {command_name}"
        fields["kind"] = "command"
        fields["command_id"] = frame.value
        fields["command_name"] = command_name
    else:
        summary = f"{rate_label} THROTTLE {frame.value}"
        fields["kind"] = "throttle"
        fields["throttle"] = frame.value

    if frame.telemetry_request:
        summary += " telemetry=1"

    return ProtocolEvent(
        timestamp_ps=frame.start_ps,
        protocol="dshot",
        summary=summary,
        fields=fields,
    )


def _decode_dshot_reply(
    capture: DigitalCapture,
    data_pin: int,
    frame: DShotFrame,
    pole_count: Optional[int],
) -> Optional[ProtocolEvent]:
    reply_period_ps = int(round(frame.bit_period_ps * 4 / 5))
    sweep_step_ps = max(reply_period_ps // 4, 1)
    best_event: Optional[ProtocolEvent] = None
    best_score: Optional[int] = None

    search_start_ps = frame.end_ps + DSHOT_REPLY_DELAY_MIN_PS
    search_end_ps = frame.end_ps + DSHOT_REPLY_DELAY_MAX_PS
    candidate_start_ps = search_start_ps

    while candidate_start_ps <= search_end_ps:
        wire_bits = [
            _sample_pin_at(
                capture,
                data_pin,
                candidate_start_ps + ((2 * index + 1) * reply_period_ps) // 2,
            )
            for index in range(DSHOT_REPLY_BITS)
        ]
        if 3 <= _transition_count(wire_bits) <= 20:
            candidate_event = _build_dshot_reply_event(
                capture,
                data_pin=data_pin,
                frame=frame,
                pole_count=pole_count,
                reply_start_ps=candidate_start_ps,
                reply_period_ps=reply_period_ps,
                wire_bits=wire_bits,
            )
            if candidate_event is not None:
                candidate_score = abs(candidate_start_ps - (frame.end_ps + DSHOT_REPLY_DELAY_TARGET_PS))
                if best_score is None or candidate_score < best_score:
                    best_score = candidate_score
                    best_event = candidate_event

        candidate_start_ps += sweep_step_ps

    return best_event


def _build_dshot_reply_event(
    capture: DigitalCapture,
    data_pin: int,
    frame: DShotFrame,
    pole_count: Optional[int],
    reply_start_ps: int,
    reply_period_ps: int,
    wire_bits: list[int],
) -> Optional[ProtocolEvent]:
    gcr_bits = [wire_bits[index] ^ wire_bits[index + 1] for index in range(len(wire_bits) - 1)]
    decoded_word = _decode_dshot_gcr_word(gcr_bits)
    if decoded_word is None:
        decoded_word = _decode_dshot_gcr_word(list(reversed(gcr_bits)))
        if decoded_word is None:
            return None

    data12 = decoded_word >> 4
    sample_index = _sample_index_at(capture, reply_start_ps)
    rate_label = _bdshot_rate_label(frame.rate)
    base_fields: dict[str, Any] = {
        "pin": data_pin,
        "rate": frame.rate,
        "shared_line": True,
        "word": f"0x{decoded_word:04X}",
        "data": f"0x{data12:03X}",
        "sample_index": sample_index,
        "reply_period_ps": reply_period_ps,
        "reply_to_forward_sample_index": frame.start_sample_index,
    }

    prefix = data12 >> 8
    if prefix == 0 or prefix & 0x01:
        protocol = "bdshot"
        fields = _build_dshot_erpm_fields(data12, pole_count)
        summary = fields.pop("summary")
        summary = f"{rate_label} {summary}"
    else:
        protocol = "edt"
        fields = _build_edt_fields(frame, data12)
        summary = fields.pop("summary")
        summary = f"EDT {rate_label} {summary}"

    return ProtocolEvent(
        timestamp_ps=reply_start_ps,
        protocol=protocol,
        summary=summary,
        fields={**base_fields, **fields},
    )


def _decode_dshot_gcr_word(gcr_bits: list[int]) -> Optional[int]:
    if len(gcr_bits) != 20:
        return None

    word = 0
    for offset in range(0, len(gcr_bits), 5):
        symbol = _bits_to_int(gcr_bits[offset:offset + 5], bit_order="msb")
        nibble = DSHOT_GCR_DECODE.get(symbol)
        if nibble is None:
            return None
        word = (word << 4) | nibble

    if (word & 0x0F) != _dshot_checksum(word >> 4):
        return None
    return word


def _build_dshot_erpm_fields(data12: int, pole_count: Optional[int]) -> dict[str, Any]:
    if data12 == 0xFFF:
        return {
            "kind": "erpm",
            "zero_rpm": True,
            "summary": "ZERO_RPM",
        }

    exponent = (data12 >> 9) & 0x07
    mantissa = data12 & 0x1FF
    period_code = mantissa << exponent
    if period_code <= 0:
        raise ValueError("Invalid bidirectional DShot period code")

    electrical_rpm_per_100 = int(round(600000 / period_code))
    electrical_rpm = electrical_rpm_per_100 * 100
    fields: dict[str, Any] = {
        "kind": "erpm",
        "zero_rpm": False,
        "period_code": period_code,
        "exponent": exponent,
        "mantissa": mantissa,
        "electrical_rpm_per_100": electrical_rpm_per_100,
        "electrical_rpm": electrical_rpm,
        "summary": f"eRPM {electrical_rpm}",
    }

    if pole_count is not None:
        mechanical_rpm = int(round(electrical_rpm / (pole_count / 2.0)))
        fields["pole_count"] = pole_count
        fields["mechanical_rpm"] = mechanical_rpm
        fields["summary"] += f" mech_RPM {mechanical_rpm}"

    return fields


def _build_edt_fields(frame: DShotFrame, data12: int) -> dict[str, Any]:
    prefix = data12 >> 8
    value = data12 & 0xFF

    if prefix == 0x2:
        return {
            "kind": "temperature",
            "temperature_c": value,
            "summary": f"TEMP {value}C",
        }
    if prefix == 0x4:
        voltage = value * 0.25
        return {
            "kind": "voltage",
            "voltage_v": round(voltage, 4),
            "summary": f"VOLTAGE {voltage:.2f}V",
        }
    if prefix == 0x6:
        return {
            "kind": "current",
            "current_a": value,
            "summary": f"CURRENT {value}A",
        }
    if prefix == 0x8:
        return {
            "kind": "debug1",
            "debug_value": value,
            "summary": f"DEBUG1 {value}",
        }
    if prefix == 0xA:
        return {
            "kind": "debug2",
            "debug_value": value,
            "summary": f"DEBUG2 {value}",
        }
    if prefix == 0xC:
        return {
            "kind": "stress",
            "stress_level": value,
            "summary": f"STRESS {value}",
        }
    if prefix == 0xE and frame.value == 13:
        return {
            "kind": "ack",
            "ack_for_command": frame.value,
            "version": value,
            "summary": f"ACK version {value}",
        }

    alert = bool(value & 0x80)
    warning = bool(value & 0x40)
    error = bool(value & 0x20)
    max_stress = value & 0x0F
    return {
        "kind": "status",
        "alert": alert,
        "warning": warning,
        "error": error,
        "max_stress": max_stress,
        "summary": (
            f"STATUS alert={int(alert)} warning={int(warning)} "
            f"error={int(error)} stress={max_stress}"
        ),
    }


def _sample_index_at(capture: DigitalCapture, time_ps: int) -> int:
    index = bisect_right(capture.timestamps_ps, time_ps) - 1
    if index < 0:
        index = 0
    return capture.sample_indexes[index]


def _transition_count(bits: list[int]) -> int:
    return sum(1 for index in range(1, len(bits)) if bits[index] != bits[index - 1])


def _dshot_rate_label(rate: int) -> str:
    return f"DShot{rate}"


def _bdshot_rate_label(rate: int) -> str:
    return f"BDShot{rate}"


def _sample_pin_at(capture: DigitalCapture, pin: int, time_ps: int) -> int:
    index = bisect_right(capture.timestamps_ps, time_ps) - 1
    if index < 0:
        index = 0
    return _snapshot_pin(capture.snapshots[index], pin)


def _snapshot_pin(snapshot: int, pin: int) -> int:
    return (snapshot >> pin) & 1


def _bits_to_int(bits: list[int], bit_order: str) -> int:
    value = 0

    if bit_order == "lsb":
        for index, bit in enumerate(bits):
            value |= (bit & 1) << index
        return value

    for bit in bits:
        value = (value << 1) | (bit & 1)
    return value


def _uart_ascii(value: int) -> Optional[str]:
    if 32 <= value <= 126:
        return chr(value)
    return None


def _spi_sample_edge(previous: int, current: int, cpol: int, cpha: int) -> bool:
    leading = previous == cpol and current == (1 - cpol)
    trailing = previous == (1 - cpol) and current == cpol
    return trailing if cpha else leading


def _cs_active(snapshot: int, cs_pin: Optional[int], active_level: int) -> bool:
    if cs_pin is None:
        return True
    return _snapshot_pin(snapshot, cs_pin) == active_level


def _validate_pin(pin: int) -> None:
    if pin < 0 or pin >= 30:
        raise ValueError("GPIO pin must be between 0 and 29")
