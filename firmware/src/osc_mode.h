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
 * Apply oscilloscope-mode configuration payload from CMD_CONFIG.
 *
 * @param payload Configuration payload
 * @param length Payload length
 * @return true if the payload was accepted
 */
bool osc_mode_apply_config(const uint8_t *payload, uint16_t length);

/**
 * Apply trigger configuration payload from CMD_TRIGGER.
 *
 * @param payload Trigger payload
 * @param length Payload length
 * @return true if the payload was accepted
 */
bool osc_mode_apply_trigger_config(const uint8_t *payload, uint16_t length);

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
