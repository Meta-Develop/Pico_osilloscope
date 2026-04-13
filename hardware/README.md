# Hardware

Hat board design files for the Pico Oscilloscope.

## Overview

The hat board stacks directly on a target Raspberry Pi Pico 2, routing all GPIO pins
to the oscilloscope Pico 2 for monitoring.

## Design Files

*(KiCad design files will be added in a future phase)*

## Pin Header Layout

The hat connects the oscilloscope Pico's GPIO pins one-to-one with the target Pico's
GPIO pins via the 40-pin headers. See `README.md` in the project root for the
complete pin mapping.

## Signal Considerations

- All signals are 3.3V CMOS logic
- No level shifting needed for Pico-to-Pico monitoring
- For higher voltage targets, voltage dividers should be added to the hat PCB
- Maximum input voltage: 3.6V (absolute maximum for RP2350)
