"""Pico Oscilloscope - PC Application Entry Point."""

from __future__ import annotations

import argparse
import sys

import serial.tools.list_ports

from serial_reader import SerialReader, MsgType


def list_ports() -> list[str]:
    """List available serial ports."""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]


def find_pico_port() -> str | None:
    """Try to find a Pico serial port automatically."""
    ports = serial.tools.list_ports.comports()
    for p in ports:
        desc = (p.description or "").lower()
        if "pico" in desc or "cdc" in desc or "2e8a" in (p.vid and hex(p.vid) or ""):
            return p.device
    return None


def run_cli(port: str) -> None:
    """Simple CLI mode for testing serial communication."""
    print(f"Connecting to {port}...")
    reader = SerialReader(port)
    print("Connected. Sending start command...")
    reader.start_sampling()

    try:
        while True:
            frames = reader.read_frames()
            for frame in frames:
                if frame.msg_type == MsgType.PIN_DATA:
                    # Each sample is 4 bytes (uint32 GPIO bitmask)
                    n_samples = len(frame.payload) // 4
                    print(f"[PIN] {n_samples} samples, first: 0x{int.from_bytes(frame.payload[:4], 'little'):08X}")
                elif frame.msg_type == MsgType.ADC_DATA:
                    n_samples = len(frame.payload) // 2
                    print(f"[ADC] {n_samples} samples")
                elif frame.msg_type == MsgType.STATUS:
                    print(f"[STATUS] {frame.payload.hex()}")
                elif frame.msg_type == MsgType.ERROR:
                    print(f"[ERROR] {frame.payload.hex()}")
    except KeyboardInterrupt:
        print("\nStopping...")
        reader.stop_sampling()
        reader.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pico Oscilloscope PC App")
    parser.add_argument("-p", "--port", type=str, help="Serial port (e.g., COM3)")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode (no GUI)")
    args = parser.parse_args()

    if args.list_ports:
        ports = list_ports()
        if not ports:
            print("No serial ports found.")
        else:
            for p in ports:
                print(p)
        return

    port = args.port or find_pico_port()
    if not port:
        print("No Pico found. Use --port to specify, or --list-ports to see available ports.")
        sys.exit(1)

    if args.cli:
        run_cli(port)
    else:
        # GUI mode (to be implemented)
        print("GUI mode not yet implemented. Use --cli for command line mode.")
        run_cli(port)


if __name__ == "__main__":
    main()
