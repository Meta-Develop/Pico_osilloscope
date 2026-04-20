/**
 * status_led.c — Onboard Status LED Patterns
 *
 * Uses simple blink signatures so USB wait, idle mode, active capture,
 * and overflow alerts are visible without a host connection.
 */

#include "status_led.h"
#include "config.h"
#include "hardware/gpio.h"
#include "pico/stdlib.h"
#include <stdbool.h>

typedef struct {
    bool level;
    uint16_t duration_ms;
} status_led_phase_t;

typedef struct {
    const status_led_phase_t *phases;
    uint8_t phase_count;
} status_led_pattern_t;

#define STATUS_LED_ALERT_DURATION_US 1500000ull

static const status_led_phase_t waiting_usb_phases[] = {
    { true, 80 },
    { false, 920 },
};

static const status_led_phase_t idle_hat_phases[] = {
    { true, 70 },
    { false, 130 },
    { true, 70 },
    { false, 730 },
};

static const status_led_phase_t idle_osc_phases[] = {
    { true, 70 },
    { false, 100 },
    { true, 70 },
    { false, 100 },
    { true, 70 },
    { false, 590 },
};

static const status_led_phase_t active_hat_phases[] = {
    { true, 900 },
    { false, 100 },
};

static const status_led_phase_t active_osc_phases[] = {
    { true, 360 },
    { false, 70 },
    { true, 360 },
    { false, 210 },
};

static const status_led_phase_t overflow_alert_phases[] = {
    { true, 50 },
    { false, 50 },
    { true, 50 },
    { false, 50 },
    { true, 50 },
    { false, 250 },
};

static const status_led_pattern_t waiting_usb_pattern = {
    .phases = waiting_usb_phases,
    .phase_count = (uint8_t)(sizeof(waiting_usb_phases) / sizeof(waiting_usb_phases[0])),
};

static const status_led_pattern_t idle_hat_pattern = {
    .phases = idle_hat_phases,
    .phase_count = (uint8_t)(sizeof(idle_hat_phases) / sizeof(idle_hat_phases[0])),
};

static const status_led_pattern_t idle_osc_pattern = {
    .phases = idle_osc_phases,
    .phase_count = (uint8_t)(sizeof(idle_osc_phases) / sizeof(idle_osc_phases[0])),
};

static const status_led_pattern_t active_hat_pattern = {
    .phases = active_hat_phases,
    .phase_count = (uint8_t)(sizeof(active_hat_phases) / sizeof(active_hat_phases[0])),
};

static const status_led_pattern_t active_osc_pattern = {
    .phases = active_osc_phases,
    .phase_count = (uint8_t)(sizeof(active_osc_phases) / sizeof(active_osc_phases[0])),
};

static const status_led_pattern_t overflow_alert_pattern = {
    .phases = overflow_alert_phases,
    .phase_count = (uint8_t)(sizeof(overflow_alert_phases) / sizeof(overflow_alert_phases[0])),
};

static status_led_state_t current_state = STATUS_LED_WAITING_USB;
static const status_led_pattern_t *active_pattern = NULL;
static uint8_t active_phase_index = 0;
static uint64_t phase_deadline_us = 0;
static uint64_t overflow_alert_until_us = 0;

static const status_led_pattern_t *status_led_base_pattern(void) {
    switch (current_state) {
    case STATUS_LED_IDLE_HAT:
        return &idle_hat_pattern;
    case STATUS_LED_IDLE_OSC:
        return &idle_osc_pattern;
    case STATUS_LED_ACTIVE_HAT:
        return &active_hat_pattern;
    case STATUS_LED_ACTIVE_OSC:
        return &active_osc_pattern;
    case STATUS_LED_WAITING_USB:
    default:
        return &waiting_usb_pattern;
    }
}

static const status_led_pattern_t *status_led_select_pattern(uint64_t now_us) {
    if (overflow_alert_until_us > now_us) {
        return &overflow_alert_pattern;
    }

    return status_led_base_pattern();
}

static void status_led_apply_pattern(const status_led_pattern_t *pattern, uint64_t now_us) {
    if (pattern == NULL || pattern->phase_count == 0) {
        gpio_put(GPIO_LED, false);
        active_pattern = NULL;
        active_phase_index = 0;
        phase_deadline_us = now_us;
        return;
    }

    active_pattern = pattern;
    active_phase_index = 0;
    gpio_put(GPIO_LED, pattern->phases[0].level);
    phase_deadline_us = now_us + ((uint64_t)pattern->phases[0].duration_ms * 1000ull);
}

void status_led_init(void) {
    gpio_init(GPIO_LED);
    gpio_set_dir(GPIO_LED, GPIO_OUT);
    gpio_put(GPIO_LED, false);

    current_state = STATUS_LED_WAITING_USB;
    overflow_alert_until_us = 0;
    status_led_apply_pattern(&waiting_usb_pattern, time_us_64());
}

void status_led_set_state(status_led_state_t state) {
    uint64_t now_us = time_us_64();

    current_state = state;

    if (overflow_alert_until_us <= now_us) {
        status_led_apply_pattern(status_led_base_pattern(), now_us);
    }
}

void status_led_signal_overflow(void) {
    uint64_t now_us = time_us_64();

    overflow_alert_until_us = now_us + STATUS_LED_ALERT_DURATION_US;
    status_led_apply_pattern(&overflow_alert_pattern, now_us);
}

void status_led_update(void) {
    uint64_t now_us = time_us_64();
    const status_led_pattern_t *desired_pattern = status_led_select_pattern(now_us);

    if (desired_pattern != active_pattern) {
        status_led_apply_pattern(desired_pattern, now_us);
    }

    while (active_pattern != NULL && now_us >= phase_deadline_us) {
        const status_led_phase_t *phase;

        active_phase_index = (uint8_t)((active_phase_index + 1) % active_pattern->phase_count);
        phase = &active_pattern->phases[active_phase_index];
        gpio_put(GPIO_LED, phase->level);
        phase_deadline_us += ((uint64_t)phase->duration_ms * 1000ull);
    }
}
