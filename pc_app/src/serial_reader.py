"""
serial_reader.py — Serial Communication with Pico Oscilloscope

Binary protocol parser for USB CDC serial communication.
Handles frame encoding/decoding, CRC verification, and data conversion.
"""

import struct
import time
from typing import Optional, Tuple

import serial

# Protocol constants
PROTO_SYNC = 0xAA
PROTO_HEADER_SIZE = 4
PROTO_MAX_PAYLOAD = 4096

# Message types (Pico -> PC)
MSG_PIN_DATA = 0x01
MSG_ADC_DATA = 0x02
MSG_TRIGGER = 0x03
MSG_STATUS = 0x20
MSG_ERROR = 0xFF

# Command types (PC -> Pico)
CMD_CONFIG = 0x10
CMD_START = 0x11
CMD_STOP = 0x12
CMD_MODE = 0x13
CMD_TRIGGER = 0x14

# Modes
MODE_HAT = 0
MODE_OSCILLOSCOPE = 1

# Status codes
STATUS_OK = 0x00
STATUS_BUSY = 0x01
STATUS_ERROR = 0x02
STATUS_OVERFLOW = 0x03

# CRC-8 MAXIM
CRC8_POLY = 0x31
CRC8_INIT = 0x00


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
        except serial.SerialException as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
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

        # CRC over type + length + payload
        crc_data = header[1:]  # Skip sync byte
        if payload:
            crc_data += payload
        crc = crc8_maxim(crc_data)

        frame = header + payload + bytes([crc])

        try:
            self.ser.write(frame)
            self.ser.flush()
            return True
        except serial.SerialException:
            return False

    def receive_frame(self, timeout: Optional[float] = None) -> Optional[Tuple[int, bytes]]:
        """
        Receive and parse a single protocol frame.

        Returns (message_type, payload) or None on timeout/error.
        """
        if not self.connected:
            return None

        old_timeout = self.ser.timeout
        if timeout is not None:
            self.ser.timeout = timeout

        try:
            # Wait for sync byte
            while True:
                byte = self.ser.read(1)
                if not byte:
                    return None
                if byte[0] == PROTO_SYNC:
                    break

            # Read type + length (3 bytes)
            header = self.ser.read(3)
            if len(header) < 3:
                return None

            msg_type = header[0]
            length = struct.unpack("<H", header[1:3])[0]

            if length > PROTO_MAX_PAYLOAD:
                return None

            # Read payload
            payload = b""
            if length > 0:
                payload = self.ser.read(length)
                if len(payload) < length:
                    return None

            # Read and verify CRC
            crc_byte = self.ser.read(1)
            if len(crc_byte) < 1:
                return None

            crc_data = header + payload
            expected_crc = crc8_maxim(crc_data)

            if crc_byte[0] != expected_crc:
                return None  # CRC mismatch

            return (msg_type, payload)

        except serial.SerialException:
            return None
        finally:
            self.ser.timeout = old_timeout

    def start_sampling(self) -> bool:
        """Send start command and wait for status response."""
        if not self.send_command(CMD_START):
            return False
        return self._wait_status_ok()

    def stop_sampling(self) -> bool:
        """Send stop command and wait for status response."""
        if not self.send_command(CMD_STOP):
            return False
        return self._wait_status_ok()

    def set_mode(self, mode: int) -> bool:
        """Switch operating mode (MODE_HAT or MODE_OSCILLOSCOPE)."""
        if not self.send_command(CMD_MODE, bytes([mode])):
            return False
        return self._wait_status_ok()

    def configure_trigger(self, channel: int, mode: int, level: int) -> bool:
        """Configure edge trigger for oscilloscope mode."""
        payload = struct.pack("<BBH", channel, mode, level)
        if not self.send_command(CMD_TRIGGER, payload):
            return False
        return self._wait_status_ok()

    def _wait_status_ok(self, timeout: float = 2.0) -> bool:
        """Wait for a STATUS_OK response."""
        result = self.receive_frame(timeout=timeout)
        if result is None:
            return False
        msg_type, payload = result
        return msg_type == MSG_STATUS and len(payload) > 0 and payload[0] == STATUS_OK

    @staticmethod
    def decode_pin_data(payload: bytes) -> list:
        """Decode PIN_DATA payload into list of 32-bit GPIO snapshots."""
        snapshots = []
        for i in range(0, len(payload), 4):
            if i + 4 <= len(payload):
                val = struct.unpack("<I", payload[i:i+4])[0]
                snapshots.append(val)
        return snapshots

    @staticmethod
    def decode_adc_data(payload: bytes) -> list:
        """Decode ADC_DATA payload into list of 16-bit sample values."""
        samples = []
        for i in range(0, len(payload), 2):
            if i + 2 <= len(payload):
                val = struct.unpack("<H", payload[i:i+2])[0]
                samples.append(val)
        return samples

    @staticmethod
    def adc_to_voltage(value: int, vref: float = 3.3) -> float:
        """Convert 12-bit ADC value to voltage."""
        return (value / 4095.0) * vref
