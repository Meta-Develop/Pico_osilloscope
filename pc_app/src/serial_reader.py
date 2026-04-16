"""Serial protocol helpers for Pico Oscilloscope."""

from dataclasses import dataclass
import struct
import time
from typing import Optional, Tuple

import serial

PROTO_SYNC = 0xAA
PROTO_HEADER_SIZE = 4
PROTO_MAX_PAYLOAD = 8192

MSG_PIN_DATA = 0x01
MSG_ADC_DATA = 0x02
MSG_TRIGGER = 0x03
MSG_PIN_BATCH = 0x04
MSG_ADC_BATCH = 0x05
MSG_STATUS = 0x20
MSG_ERROR = 0xFF

CMD_CONFIG = 0x10
CMD_START = 0x11
CMD_STOP = 0x12
CMD_MODE = 0x13
CMD_TRIGGER = 0x14

CFG_HAT_PIN_DIVIDER = 0x01
CFG_OSC_ADC_DIVIDER = 0x10
CFG_OSC_DIGITAL_ENABLE = 0x11
CFG_OSC_PIN_DIVIDER = 0x12

MODE_HAT = 0
MODE_OSCILLOSCOPE = 1

STATUS_OK = 0x00
STATUS_BUSY = 0x01
STATUS_ERROR = 0x02
STATUS_OVERFLOW = 0x03

CRC8_POLY = 0x31
CRC8_INIT = 0x00

ADC_BATCH_HEADER_SIZE = 20
PIN_BATCH_HEADER_SIZE = 24


@dataclass(slots=True)
class ADCBatch:
    start_time_ps: int
    sample_interval_ps: int
    sample_count: int
    channel_count: int
    samples: list[int]


@dataclass(slots=True)
class PinBatch:
    start_time_ps: int
    sample_interval_ps: int
    sample_count: int
    pin_mask: int
    snapshots: list[int]


def crc8_maxim(data: bytes) -> int:
    """Compute CRC-8 MAXIM checksum."""
    crc = CRC8_INIT
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ CRC8_POLY) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


class SerialReader:
    """Serial communication handler for Pico Oscilloscope."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

    def connect(self) -> bool:
        """Open serial connection."""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
            return True
        except serial.SerialException as exc:
            print(f"Connection failed: {exc}")
            return False

    def disconnect(self) -> None:
        """Close serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.ser = None

    @property
    def connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def send_command(self, cmd_type: int, payload: bytes = b"") -> bool:
        """Send a command frame to the Pico."""
        if not self.connected:
            return False

        length = len(payload)
        header = struct.pack("<BBH", PROTO_SYNC, cmd_type, length)
        crc = crc8_maxim(header[1:] + payload)
        frame = header + payload + bytes([crc])

        try:
            self.ser.write(frame)
            self.ser.flush()
            return True
        except serial.SerialException:
            return False

    def receive_frame(self, timeout: Optional[float] = None) -> Optional[Tuple[int, bytes]]:
        """Receive and parse a single protocol frame."""
        if not self.connected:
            return None

        old_timeout = self.ser.timeout
        if timeout is not None:
            self.ser.timeout = timeout

        try:
            while True:
                byte = self.ser.read(1)
                if not byte:
                    return None
                if byte[0] == PROTO_SYNC:
                    break

            header = self.ser.read(3)
            if len(header) < 3:
                return None

            msg_type = header[0]
            length = struct.unpack("<H", header[1:3])[0]
            if length > PROTO_MAX_PAYLOAD:
                return None

            payload = self.ser.read(length) if length > 0 else b""
            if len(payload) < length:
                return None

            crc_byte = self.ser.read(1)
            if len(crc_byte) < 1:
                return None

            expected_crc = crc8_maxim(header + payload)
            if crc_byte[0] != expected_crc:
                return None

            return msg_type, payload
        except serial.SerialException:
            return None
        finally:
            self.ser.timeout = old_timeout

    def start_sampling(self) -> bool:
        """Send start command and wait for status response."""
        return self._send_command_and_wait_ok(CMD_START)

    def stop_sampling(self) -> bool:
        """Send stop command and wait for status response."""
        return self._send_command_and_wait_ok(CMD_STOP)

    def set_mode(self, mode: int) -> bool:
        """Switch operating mode."""
        return self._send_command_and_wait_ok(CMD_MODE, bytes([mode]))

    def configure_trigger(self, channel: int, mode: int, level: int) -> bool:
        """Configure edge trigger for oscilloscope mode."""
        payload = struct.pack("<BBH", channel, mode, level)
        return self._send_command_and_wait_ok(CMD_TRIGGER, payload)

    def configure_hat_divider(self, divider: float) -> bool:
        """Configure the hat-mode PIO divider."""
        payload = bytes([CFG_HAT_PIN_DIVIDER]) + struct.pack("<f", divider)
        return self._send_command_and_wait_ok(CMD_CONFIG, payload)

    def configure_adc_divider(self, divider: int) -> bool:
        """Configure the oscilloscope ADC divider."""
        payload = struct.pack("<BH", CFG_OSC_ADC_DIVIDER, divider)
        return self._send_command_and_wait_ok(CMD_CONFIG, payload)

    def configure_digital_enabled(self, enabled: bool) -> bool:
        """Enable or disable oscilloscope-mode digital capture."""
        payload = struct.pack("<BBB", CFG_OSC_DIGITAL_ENABLE, int(enabled), 0)
        return self._send_command_and_wait_ok(CMD_CONFIG, payload)

    def configure_osc_digital_divider(self, divider: float) -> bool:
        """Configure the oscilloscope-mode digital PIO divider."""
        payload = bytes([CFG_OSC_PIN_DIVIDER]) + struct.pack("<f", divider)
        return self._send_command_and_wait_ok(CMD_CONFIG, payload)

    def _send_command_and_wait_ok(self, cmd_type: int, payload: bytes = b"") -> bool:
        """Send a command frame and wait for a STATUS_OK response."""
        if not self.send_command(cmd_type, payload):
            return False
        return self._wait_status_ok()

    def _wait_status_ok(self, timeout: float = 2.0) -> bool:
        """Wait for a STATUS_OK response."""
        end_time = time.monotonic() + timeout

        while time.monotonic() < end_time:
            remaining = end_time - time.monotonic()
            result = self.receive_frame(timeout=max(0.05, remaining))
            if result is None:
                continue

            msg_type, payload = result
            if msg_type == MSG_STATUS and len(payload) > 0:
                return payload[0] == STATUS_OK

        return False

    @staticmethod
    def decode_pin_data(payload: bytes) -> list[int]:
        """Decode a legacy PIN_DATA payload."""
        count = len(payload) // 4
        if count == 0:
            return []
        return list(struct.unpack(f"<{count}I", payload[: count * 4]))

    @staticmethod
    def decode_adc_data(payload: bytes) -> list[int]:
        """Decode a legacy ADC_DATA payload."""
        count = len(payload) // 2
        if count == 0:
            return []
        return list(struct.unpack(f"<{count}H", payload[: count * 2]))

    @staticmethod
    def decode_adc_batch(payload: bytes) -> Optional[ADCBatch]:
        """Decode an ADC batch payload."""
        if len(payload) < ADC_BATCH_HEADER_SIZE:
            return None

        start_time_ps, sample_interval_ps = struct.unpack_from("<QQ", payload, 0)
        sample_count = struct.unpack_from("<H", payload, 16)[0]
        channel_count = payload[18]
        expected_length = ADC_BATCH_HEADER_SIZE + sample_count * 2
        if len(payload) < expected_length:
            return None

        samples = SerialReader.decode_adc_data(payload[ADC_BATCH_HEADER_SIZE:expected_length])
        return ADCBatch(
            start_time_ps=start_time_ps,
            sample_interval_ps=sample_interval_ps,
            sample_count=sample_count,
            channel_count=channel_count,
            samples=samples,
        )

    @staticmethod
    def decode_pin_batch(payload: bytes) -> Optional[PinBatch]:
        """Decode a GPIO batch payload."""
        if len(payload) < PIN_BATCH_HEADER_SIZE:
            return None

        start_time_ps, sample_interval_ps = struct.unpack_from("<QQ", payload, 0)
        sample_count = struct.unpack_from("<H", payload, 16)[0]
        pin_mask = struct.unpack_from("<I", payload, 18)[0]
        expected_length = PIN_BATCH_HEADER_SIZE + sample_count * 4
        if len(payload) < expected_length:
            return None

        snapshots = SerialReader.decode_pin_data(payload[PIN_BATCH_HEADER_SIZE:expected_length])
        return PinBatch(
            start_time_ps=start_time_ps,
            sample_interval_ps=sample_interval_ps,
            sample_count=sample_count,
            pin_mask=pin_mask,
            snapshots=snapshots,
        )

    @staticmethod
    def sample_rate_from_interval_ps(interval_ps: int) -> float:
        """Convert a sample interval in picoseconds to samples per second."""
        if interval_ps <= 0:
            return 0.0
        return 1_000_000_000_000.0 / interval_ps

    @staticmethod
    def adc_to_voltage(value: int, vref: float = 3.3) -> float:
        """Convert a 12-bit ADC reading to volts."""
        return (value / 4095.0) * vref
