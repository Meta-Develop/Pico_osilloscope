/**
 * osc_mode.h — Oscilloscope Mode: 4ch Analog + Digital
 *
 * ADC0-ADC3 for analog waveform capture.
 * Remaining GPIO as digital logic channels.
 */

#ifndef OSC_MODE_H
#define OSC_MODE_H

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize oscilloscope mode.
 * Sets up ADC for 4-channel analog and PIO for digital monitoring.
 */
void osc_mode_init(void);

/**
 * Run oscilloscope mode main loop (blocking).
 * Streams ADC + digital data over USB.
 * Returns when CMD_STOP or CMD_MODE received.
 *
 * @return New mode, or -1 if stopped
 */
int osc_mode_run(void);

/**
 * Stop oscilloscope mode.
 */
void osc_mode_stop(void);

#endif /* OSC_MODE_H */
