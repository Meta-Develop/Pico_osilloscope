#ifndef PICO_OSC_PIN_MONITOR_H
#define PICO_OSC_PIN_MONITOR_H

#include <stdint.h>
#include <stdbool.h>

/* Initialize GPIO pins for digital monitoring (input, hi-Z) */
void pin_monitor_init(void);

/* Sample all monitored GPIO pins. Returns a 32-bit bitmask of pin states. */
uint32_t pin_monitor_sample(void);

/* Start periodic pin sampling at the given rate */
void pin_monitor_start(uint32_t sample_rate_hz);

/* Stop periodic sampling */
void pin_monitor_stop(void);

/* Check if a sample batch is ready */
bool pin_monitor_data_ready(void);

/* Get sampled pin data. Returns number of samples written to buf.
   Each sample is a 32-bit bitmask of GPIO states. */
uint32_t pin_monitor_get_data(uint32_t *buf, uint32_t max_samples);

/* Set which GPIO pins to monitor (bitmask) */
void pin_monitor_set_mask(uint32_t gpio_mask);

/* Get current monitoring mask */
uint32_t pin_monitor_get_mask(void);

#endif /* PICO_OSC_PIN_MONITOR_H */
