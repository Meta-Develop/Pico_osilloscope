#include "hat_mode.h"
#include "config.h"
#include "pin_monitor.h"
#include "adc_sampler.h"
#include "usb_comm.h"

#include <string.h>

static bool active = false;

void hat_mode_init(void) {
    pin_monitor_init();
    adc_sampler_init();
}

void hat_mode_start(void) {
    pin_monitor_start(PIN_MONITOR_SAMPLE_HZ);
    adc_sampler_start(ADC_SAMPLE_RATE_HZ);
    active = true;
}

void hat_mode_stop(void) {
    pin_monitor_stop();
    adc_sampler_stop();
    active = false;
}

void hat_mode_tick(void) {
    if (!active) return;

    /* Send digital pin data */
    if (pin_monitor_data_ready()) {
        uint32_t samples[64];
        uint32_t count = pin_monitor_get_data(samples, 64);
        if (count > 0) {
            /* Pack: 4 bytes per sample (32-bit GPIO bitmask) */
            usb_comm_send(MSG_PIN_DATA,
                          (const uint8_t *)samples,
                          (uint16_t)(count * sizeof(uint32_t)));
        }
    }

    /* Send ADC data */
    if (adc_sampler_buffer_ready()) {
        uint32_t len = 0;
        const uint16_t *buf = adc_sampler_get_buffer(&len);
        if (buf != NULL && len > 0) {
            usb_comm_send(MSG_ADC_DATA,
                          (const uint8_t *)buf,
                          (uint16_t)(len * sizeof(uint16_t)));
            adc_sampler_release_buffer();
        }
    }
}

bool hat_mode_is_active(void) {
    return active;
}
