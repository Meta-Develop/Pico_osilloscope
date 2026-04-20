# Pico Oscilloscope

Simple oscilloscope and logic analyzer built on Raspberry Pi Pico 2 (RP2350).

## Features

- **Hat Mode**: Stacks on a target Pico 2, monitors all GPIO pins as digital logic (27 channels)
- **Oscilloscope Mode**: 4-channel 12-bit analog (ADC0-ADC3) + 23 digital channels
- **High-Speed Sampling**: PIO-based digital capture tracks `clk_sys` and defaults to a 360 MHz target build clock
- **Protocol Analyzer**: Offline UART, I2C, and SPI decode from digital capture CSV exports
- **CLI Interface**: Command-line tool for capture, monitoring, and export
- **CSV Export**: Machine-readable output for post-analysis
- **JSON Status**: Programmatic access for automation and scripting

Digital snapshots currently require 2 PIO cycles per sample, so a 360 MHz `clk_sys` build yields a
180 MHz theoretical GPIO sample clock. Sustained streaming is still limited by USB CDC throughput, so
use `--pin-divider` to reduce digital sample rate for long captures.

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
cmake -B build -G Ninja -DPICO_OSC_TARGET_SYS_CLOCK_KHZ=360000
cmake --build build
build/_deps/picotool-build/picotool uf2 convert \
    build/src/pico_oscilloscope.bin build/src/pico_oscilloscope.uf2 \
    -o 0x10000000 --family 0xe48bff59 --abs-block
```

Lower clock targets remain available, for example `-DPICO_OSC_TARGET_SYS_CLOCK_KHZ=300000`.

Output: `firmware/build/src/pico_oscilloscope.uf2`

### Flashing

1. Hold **BOOTSEL** on the Pico 2 and connect USB
2. Copy `pico_oscilloscope.uf2` to the `RP2350` drive

### PC Application

Requires: Python 3.10+

```bash
pip install -r pc_app/requirements.txt
```

## CLI Usage

Commands that talk to the Pico require `--port` (`-p`) to specify the serial port.

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

# Hat mode: longer capture at a lower digital sample rate
python pc_app/src/main.py -p COM3 capture --mode hat --duration 5 \
    --pin-divider 128 --output hat_data.csv

# Oscilloscope mode: capture with rising edge trigger
python pc_app/src/main.py -p COM3 capture --mode oscilloscope --duration 10 \
    --output scope_data.csv --trigger rising --channel 0 --level 2048

# Oscilloscope mode: analog only
python pc_app/src/main.py -p COM3 capture --mode oscilloscope --digital off \
    --duration 5 --output scope_analog_only.csv

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

# Oscilloscope mode with digital capture disabled
python pc_app/src/main.py -p COM3 monitor --mode oscilloscope --digital off

# Oscilloscope mode with slower digital capture for mixed analog/digital streaming
python pc_app/src/main.py -p COM3 monitor --mode oscilloscope --digital on --pin-divider 64
```

### Device Configuration

```bash
# Switch to oscilloscope mode
python pc_app/src/main.py -p COM3 config --mode oscilloscope

# Configure trigger
python pc_app/src/main.py -p COM3 config --trigger rising --channel 0 --level 2048

# Toggle oscilloscope digital capture
python pc_app/src/main.py -p COM3 config --digital off
```

## Protocol Analyzer

Decode digital captures exported from hat mode, including edge-compressed CSV exports, or any CSV that contains GPIO columns and timestamps.

Current protocol decoders:

- UART
- I2C
- SPI
- DShot150, DShot300, DShot600 forward frames
- Shared-line bidirectional DShot telemetry (eRPM / zero-RPM)
- Extended DShot Telemetry (EDT) typed replies such as temperature, voltage, current, stress, and status frames

All protocol decoders are available from the CLI today through `python pc_app/src/main.py protocol ...`. The GUI does not expose protocol decoding yet.

```bash
# UART decode from GPIO1 at 115200 baud
python pc_app/src/main.py protocol --input hat_data.csv uart \
    --data-pin 1 --baud 115200

# I2C decode from GPIO2/GPIO3
python pc_app/src/main.py protocol --input hat_data.csv i2c \
    --scl-pin 3 --sda-pin 2

# SPI mode 0 decode with MOSI on GPIO7 and MISO on GPIO4
python pc_app/src/main.py protocol --input hat_data.csv spi \
    --clock-pin 6 --mosi-pin 7 --miso-pin 4 --cs-pin 5 --spi-mode 0

# DShot600 forward decode on GPIO4
python pc_app/src/main.py protocol --input hat_data.csv dshot \
    --data-pin 4 --dshot-rate 600

# Auto-detect DShot150/300/600 from the capture timing
python pc_app/src/main.py protocol --input hat_data.csv dshot \
    --data-pin 4 --dshot-rate auto

# Shared-line bidirectional DShot with EDT / eRPM telemetry
python pc_app/src/main.py protocol --input hat_data.csv dshot \
    --data-pin 4 --dshot-rate 600 --bidirectional --pole-count 14

# Export hat-mode edges only, then decode them later
python pc_app/src/main.py -p COM3 capture --mode hat --duration 1 \
    --digital-export edge --output hat_edges.csv
```

`--bidirectional` switches the decoder to shared-line bidirectional DShot mode. In that mode the forward command is decoded from the inverted signal, then the analyzer searches for the ESC reply about 20-45 us later and attempts to decode eRPM or EDT frames from the same pin.

`--pole-count` is optional. When it is provided, bidirectional DShot eRPM replies also report estimated mechanical RPM.

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
- **Timestamp X-Axis**: Plot time is based on firmware batch timestamps instead of sample index
- **Trigger Control**: Interactive trigger level line (draggable), edge mode selection
- **Channel Toggles**: Enable/disable individual ADC channels
- **Digital Toggle in Oscilloscope Mode**: Turn digital capture on or off while analog streaming continues
- **Adjustable Buffer**: Configure display depth (256 – 16384 samples)
- **Dark Theme**: Oscilloscope-style dark background with high-contrast traces
- **Live Stats**: Received sample rates, configured rates, and UI FPS counter

### Mode Switching

- **Hat Mode**: Shows digital logic analyzer only (all 27 monitored GPIO pins)
- **Oscilloscope Mode**: Split view with analog waveforms (top) and digital logic (bottom)

## CSV Format

### Hat Mode CSV

```csv
index,raw_sample_index,timestamp,timestamp_ps,gpio_raw,GPIO0,GPIO1,...,GPIO29
0,0,0.000001000000,1000000,0x20000001,1,0,...,1
1,1,0.000002000000,2000000,0x00000003,1,1,...,0
```

Each row is a GPIO snapshot. `index` is the row index in the exported file. `raw_sample_index` is the original sample position in the raw hat-mode stream. Each GPIO column is 0 or 1.

### Hat Mode Edge-Compressed CSV

```csv
index,raw_sample_index,delta_samples,timestamp,timestamp_ps,delta_time_ps,gpio_raw,changed_mask,GPIO0,GPIO1,...,GPIO29
0,0,0,0.000001000000,1000000,0,0x20000001,0x00000000,1,0,...,1
1,14,14,0.000015000000,15000000,14000000,0x20000003,0x00000002,1,1,...,1
```

Use `python pc_app/src/main.py capture --mode hat --digital-export edge` to emit only the first sample and rows where the GPIO state changes. `delta_samples` and `delta_time_ps` show how long the previous state persisted.

### Oscilloscope Mode CSV

```csv
index,timestamp,timestamp_ps,channel,raw,voltage
0,0.000001000000,1000000,0,2048,1.6500
1,0.000001000000,1000000,1,1024,0.8250
```

Samples are interleaved by channel in round-robin order.

## JSON Output Format

When using `--format json` with the `monitor` command, each line is a JSON object:

```json
{"type": "pin", "timestamp": "2025-01-15T10:30:00.123", "gpio_raw": 1234567, "pins": {"GPIO0": 1, "GPIO1": 0, ...}}
{"type": "adc", "timestamp": "2025-01-15T10:30:00.124", "channel": 0, "raw": 2048, "voltage": 1.6500}
{"type": "trigger", "timestamp": "2025-01-15T10:30:00.125"}
```

Oscilloscope and hat monitoring now also emit batch-oriented JSON records for high-throughput streams:

```json
{"type": "pin_batch", "start_time_ps": 0, "sample_interval_ps": 13333, "sample_count": 2042, "pin_mask": 4194303, "snapshots": [123, 456]}
{"type": "adc_batch", "start_time_ps": 0, "sample_interval_ps": 2000000, "sample_count": 4086, "channel_count": 4, "samples": [2048, 1024]}
```

## Communication Protocol

Binary frames over USB CDC serial:

```
[SYNC 0xAA] [TYPE 1B] [LENGTH 2B LE] [PAYLOAD 0-8192B] [CRC8-MAXIM 1B]
```

| Type | Value | Direction | Description |
|------|-------|-----------|-------------|
| PIN_DATA | 0x01 | Pico → PC | GPIO snapshots (32-bit each) |
| ADC_DATA | 0x02 | Pico → PC | ADC samples (16-bit each) |
| TRIGGER | 0x03 | Pico → PC | Trigger event |
| PIN_BATCH | 0x04 | Pico → PC | Timestamped GPIO snapshot batches |
| ADC_BATCH | 0x05 | Pico → PC | Timestamped ADC sample batches |
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
