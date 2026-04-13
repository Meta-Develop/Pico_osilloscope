# Pico Oscilloscope

Simple oscilloscope and logic analyzer built on Raspberry Pi Pico 2 (RP2350).

## Features

- **Hat Mode**: Stacks on a target Pico 2, monitors all GPIO pins as digital logic (27 channels)
- **Oscilloscope Mode**: 4-channel 12-bit analog (ADC0-ADC3) + 23 digital channels
- **High-Speed Sampling**: PIO-based digital capture at up to 150 MHz, ADC at 500 ksps
- **CLI Interface**: Command-line tool for capture, monitoring, and export
- **CSV Export**: Machine-readable output for post-analysis
- **JSON Status**: Programmatic access for automation and scripting

## Hardware

- **Oscilloscope Board**: Raspberry Pi Pico 2 (RP2350)
- **Target**: Any Pico 2 (or 3.3V logic device)
- **Connection**: USB CDC serial to PC, pin headers to target

### Pin Mapping

#### Hat Mode (All Digital)

All GPIO pins read as digital logic. GPIO26-29 are used as digital inputs (NOT ADC).

| Pins | Function | Count |
|------|----------|-------|
| GPIO0-22 | Digital logic | 23 |
| GPIO26-29 | Digital logic | 4 |
| GPIO25 | Status LED | 1 |

**Total monitored: 27 pins**

#### Oscilloscope Mode (Analog + Digital)

| Pins | Function | Count |
|------|----------|-------|
| GPIO26 (ADC0) | Analog CH1, 12-bit | 1 |
| GPIO27 (ADC1) | Analog CH2, 12-bit | 1 |
| GPIO28 (ADC2) | Analog CH3, 12-bit | 1 |
| GPIO29 (ADC3) | Analog CH4, 12-bit | 1 |
| GPIO0-22 | Digital logic | 23 |
| GPIO25 | Status LED | 1 |

**Total: 4 analog + 23 digital = 27 channels**

## Building

### Firmware

Requires: ARM GCC toolchain, CMake 3.13+, [Pico SDK 2.x](https://github.com/raspberrypi/pico-sdk)

```bash
cd firmware
cmake -B build -G Ninja
cmake --build build
```

Output: `firmware/build/pico_oscilloscope.uf2`

### Flashing

1. Hold **BOOTSEL** on the Pico 2 and connect USB
2. Copy `pico_oscilloscope.uf2` to the `RPI-RP2` drive

### PC Application

Requires: Python 3.10+

```bash
pip install -r pc_app/requirements.txt
```

## CLI Usage

All commands require `--port` (`-p`) to specify the serial port.

### Check Connection

```bash
python pc_app/src/main.py -p COM3 status
```

Output (JSON):
```json
{"status": "connected", "port": "COM3", "timestamp": "2025-01-15T10:30:00"}
```

### Capture to CSV

```bash
# Hat mode: capture 5 seconds of digital data
python pc_app/src/main.py -p COM3 capture --mode hat --duration 5 --output hat_data.csv

# Oscilloscope mode: capture with rising edge trigger
python pc_app/src/main.py -p COM3 capture --mode oscilloscope --duration 10 \
    --output scope_data.csv --trigger rising --channel 0 --level 2048

# Output to stdout (pipe-friendly)
python pc_app/src/main.py -p COM3 capture --mode hat --duration 2
```

### Live Monitoring

```bash
# Text output (human-readable)
python pc_app/src/main.py -p COM3 monitor --mode hat

# JSON output (machine-readable, one object per line)
python pc_app/src/main.py -p COM3 monitor --mode hat --format json

# Oscilloscope mode with JSON
python pc_app/src/main.py -p COM3 monitor --mode oscilloscope --format json
```

### Device Configuration

```bash
# Switch to oscilloscope mode
python pc_app/src/main.py -p COM3 config --mode oscilloscope

# Configure trigger
python pc_app/src/main.py -p COM3 config --trigger rising --channel 0 --level 2048
```

## GUI (Real-Time Waveform Viewer)

A PyQt6 + pyqtgraph oscilloscope-style GUI for real-time waveform visualization.

```bash
# Launch in hat mode (digital logic analyzer)
python pc_app/src/gui.py --port COM3

# Launch in oscilloscope mode (analog waveforms + digital)
python pc_app/src/gui.py --port COM3 --mode oscilloscope
```

### GUI Features

- **Analog Waveform Display**: 4-channel real-time voltage plots with per-channel color coding
- **Digital Logic Analyzer**: Multi-channel digital waveform view for all GPIO pins
- **Trigger Control**: Interactive trigger level line (draggable), edge mode selection
- **Channel Toggles**: Enable/disable individual ADC channels
- **Adjustable Buffer**: Configure display depth (256 – 16384 samples)
- **Dark Theme**: Oscilloscope-style dark background with high-contrast traces
- **Live Stats**: Sample count and FPS counter

### Mode Switching

- **Hat Mode**: Shows digital logic analyzer only (all 27 monitored GPIO pins)
- **Oscilloscope Mode**: Split view with analog waveforms (top) and digital logic (bottom)

## CSV Format

### Hat Mode CSV

```csv
index,timestamp,GPIO0,GPIO1,...,GPIO29
0,0.000001,1,0,...,1
1,0.000002,1,1,...,0
```

Each row is a GPIO snapshot. Each GPIO column is 0 or 1.

### Oscilloscope Mode CSV

```csv
index,timestamp,channel,raw,voltage
0,0.000001,0,2048,1.6500
1,0.000001,1,1024,0.8250
```

Samples are interleaved by channel in round-robin order.

## JSON Output Format

When using `--format json` with the `monitor` command, each line is a JSON object:

```json
{"type": "pin", "timestamp": "2025-01-15T10:30:00.123", "gpio_raw": 1234567, "pins": {"GPIO0": 1, "GPIO1": 0, ...}}
{"type": "adc", "timestamp": "2025-01-15T10:30:00.124", "channel": 0, "raw": 2048, "voltage": 1.6500}
{"type": "trigger", "timestamp": "2025-01-15T10:30:00.125"}
```

## Communication Protocol

Binary frames over USB CDC serial:

```
[SYNC 0xAA] [TYPE 1B] [LENGTH 2B LE] [PAYLOAD 0-4096B] [CRC8-MAXIM 1B]
```

| Type | Value | Direction | Description |
|------|-------|-----------|-------------|
| PIN_DATA | 0x01 | Pico → PC | GPIO snapshots (32-bit each) |
| ADC_DATA | 0x02 | Pico → PC | ADC samples (16-bit each) |
| TRIGGER | 0x03 | Pico → PC | Trigger event |
| CMD_START | 0x11 | PC → Pico | Start sampling |
| CMD_STOP | 0x12 | PC → Pico | Stop sampling |
| CMD_MODE | 0x13 | PC → Pico | Switch mode |
| STATUS | 0x20 | Pico → PC | Status response |

## Project Structure

```
firmware/           Pico 2 firmware (C, Pico SDK)
├── src/
│   ├── config.h        Pin mapping and protocol constants
│   ├── main.c          Entry point and mode selection
│   ├── hat_mode.c/h    All-digital GPIO monitoring
│   ├── osc_mode.c/h    4ch analog + digital monitoring
│   ├── pin_monitor.c/h PIO-based GPIO sampling
│   ├── adc_sampler.c/h DMA-based 4ch ADC sampling
│   └── usb_comm.c/h    USB CDC serial protocol
pc_app/             PC application (Python)
├── src/
│   ├── main.py         CLI interface
│   ├── gui.py          Real-time oscilloscope GUI
│   └── serial_reader.py Protocol parser
hardware/           Hat board design (KiCad)
docs/               Additional documentation
```

## License

MIT
