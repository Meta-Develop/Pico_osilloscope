#include "pin_monitor.h"
#include "config.h"

#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/timer.h"

#define SAMPLE_BUF_SIZE 2048

static uint32_t sample_buf[SAMPLE_BUF_SIZE];
static volatile uint32_t write_idx = 0;
static volatile uint32_t read_idx = 0;
static volatile bool sampling_active = false;
static uint32_t monitor_mask = 0;
static struct repeating_timer sample_timer;

static bool sample_timer_callback(struct repeating_timer *t) {
    (void)t;
    if (!sampling_active) return true;

    uint32_t next = (write_idx + 1) % SAMPLE_BUF_SIZE;
    if (next == read_idx) {
        /* Buffer full, drop sample */
        return true;
    }

    sample_buf[write_idx] = gpio_get_all() & monitor_mask;
    write_idx = next;
    return true;
}

void pin_monitor_init(void) {
    /* Build default monitor mask: GPIO0-GPIO22 */
    monitor_mask = 0;
    for (int i = PIN_MONITOR_FIRST_GPIO; i <= PIN_MONITOR_LAST_GPIO; i++) {
        monitor_mask |= (1u << i);
    }

    /* Configure all monitored pins as inputs with no pull */
    for (int i = PIN_MONITOR_FIRST_GPIO; i <= PIN_MONITOR_LAST_GPIO; i++) {
        gpio_init(i);
        gpio_set_dir(i, GPIO_IN);
        gpio_disable_pulls(i);
    }
}

uint32_t pin_monitor_sample(void) {
    return gpio_get_all() & monitor_mask;
}

void pin_monitor_start(uint32_t sample_rate_hz) {
    write_idx = 0;
    read_idx = 0;
    sampling_active = true;

    int64_t interval_us = -(int64_t)(1000000 / sample_rate_hz);
    add_repeating_timer_us(interval_us, sample_timer_callback, NULL, &sample_timer);
}

void pin_monitor_stop(void) {
    sampling_active = false;
    cancel_repeating_timer(&sample_timer);
}

bool pin_monitor_data_ready(void) {
    return write_idx != read_idx;
}

uint32_t pin_monitor_get_data(uint32_t *buf, uint32_t max_samples) {
    uint32_t count = 0;
    while (count < max_samples && read_idx != write_idx) {
        buf[count++] = sample_buf[read_idx];
        read_idx = (read_idx + 1) % SAMPLE_BUF_SIZE;
    }
    return count;
}

void pin_monitor_set_mask(uint32_t gpio_mask) {
    monitor_mask = gpio_mask;
}

uint32_t pin_monitor_get_mask(void) {
    return monitor_mask;
}
