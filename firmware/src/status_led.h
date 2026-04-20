/**
 * status_led.h — Onboard Status LED Patterns
 *
 * Encodes USB, mode, capture, and overflow states on the Pico LED.
 */

#ifndef STATUS_LED_H
#define STATUS_LED_H

#include <stdint.h>

typedef enum {
    STATUS_LED_WAITING_USB = 0,
    STATUS_LED_IDLE_HAT,
    STATUS_LED_IDLE_OSC,
    STATUS_LED_ACTIVE_HAT,
    STATUS_LED_ACTIVE_OSC,
} status_led_state_t;

void status_led_init(void);
void status_led_set_state(status_led_state_t state);
void status_led_signal_overflow(void);
void status_led_update(void);

#endif /* STATUS_LED_H */
