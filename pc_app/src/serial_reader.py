"""Pico Oscilloscope - Serial communication protocol."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

import serial


class MsgType(IntEnum):
    """Message types for Pico <-> PC communication."""

    # Pico -> PC
    PIN_DATA = 0x01
    ADC_DATA = 0x02
    WAVE_DATA = 0x03
    STATUS = 0x20
    ERROR = 0xFF

    # PC -> Pico
    CMD_CONFIG = 0x10
    CMD_START = 0x11
    CMD_STOP = 0x12
    CMD_MODE = 0x13


SYNC_BYTE = 0xAA


def crc8_maxim(data: bytes) -> int:
    """CRC-8/MAXIM (Dallas) calculation."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x01:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
    return crc


@dataclass
class Frame:
    """A decoded protocol frame."""

    msg_type: MsgType
    payload: bytes


def build_frame(msg_type: int, payload: bytes = b"") -> bytes:
    """Build a binary protocol frame."""
    length = len(payload)
    header = struct.pack("<BBH", SYNC_BYTE, msg_type, length)
    crc_data = struct.pack("<BH", msg_type, length) + payload
    crc = crc8_maxim(crc_data)
    return header + payload + struct.pack("B", crc)


class SerialReader:
    """Reads and parses framed data from a Pico via USB CDC serial."""

    def __init__(self, port: str, baudrate: int = 115200):
        self._ser = serial.Serial(port, baudrate, timeout=0.01)
        self._buf = bytearray()

    def close(self) -> None:
        self._ser.close()

    @property
    def is_open(self) -> bool:
        return self._ser.is_open

    def send_command(self, msg_type: int, payload: bytes = b"") -> None:
        """Send a command frame to the Pico."""
        frame = build_frame(msg_type, payload)
        self._ser.write(frame)
        self._ser.flush()

    def start_sampling(self) -> None:
        self.send_command(MsgType.CMD_START)

    def stop_sampling(self) -> None:
        self.send_command(MsgType.CMD_STOP)

    def set_mode(self, mode: int) -> None:
        self.send_command(MsgType.CMD_MODE, struct.pack("B", mode))

    def read_frames(self) -> list[Frame]:
        """Read available data and return any complete frames."""
        data = self._ser.read(self._ser.in_waiting or 1)
        if data:
            self._buf.extend(data)

        frames: list[Frame] = []
        while True:
            frame = self._try_parse_frame()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def _try_parse_frame(self) -> Frame | None:
        """Try to parse one frame from the internal buffer."""
        # Find sync byte
        while len(self._buf) > 0 and self._buf[0] != SYNC_BYTE:
            self._buf.pop(0)

        # Need at least: SYNC(1) + TYPE(1) + LEN(2) + CRC(1) = 5 bytes
        if len(self._buf) < 5:
            return None

        msg_type = self._buf[1]
        length = struct.unpack_from("<H", self._buf, 2)[0]

        total = 4 + length + 1  # header + payload + crc
        if len(self._buf) < total:
            return None

        payload = bytes(self._buf[4 : 4 + length])
        received_crc = self._buf[4 + length]

        # Verify CRC
        crc_data = struct.pack("<BH", msg_type, length) + payload
        expected_crc = crc8_maxim(crc_data)

        # Consume the frame from buffer
        del self._buf[:total]

        if received_crc != expected_crc:
            return None  # CRC mismatch, discard

        return Frame(msg_type=MsgType(msg_type), payload=payload)
