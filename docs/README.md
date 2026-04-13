# Documentation

Additional documentation for the Pico Oscilloscope project.

## Reference

- [Raspberry Pi Pico 2 Datasheet](https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf)
- [RP2350 Datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
- [Pico SDK Documentation](https://www.raspberrypi.com/documentation/microcontrollers/c_sdk.html)
- [PIO Programming Guide](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf#section_pio)

## Modes

### Hat Mode

All 27 usable GPIO pins are monitored as digital logic. PIO state machines
sample all pins simultaneously for high-speed capture. GPIO26-29 are explicitly
used as digital inputs, not ADC. Ideal for monitoring another Pico's bus
signals, SPI, I2C, UART, etc.

### Oscilloscope Mode

4-channel 12-bit analog sampling via ADC0-ADC3 (GPIO26-29) using DMA for
continuous capture at up to 500 ksps. Remaining GPIO0-22 serve as digital
logic channels. Supports edge-based triggering on any ADC channel.
