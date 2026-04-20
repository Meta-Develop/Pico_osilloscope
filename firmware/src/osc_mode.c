/**
 * osc_mode.c — Oscilloscope Mode: 4ch Analog + Digital
 *
 * ADC0-ADC3 (GPIO26-29): 12-bit analog sampling via DMA
 * GPIO0-22: digital logic channels via PIO
 * Supports edge-based triggering on ADC channels.
 */

#include "osc_mode.h"
#include "config.h"
#include "adc_sampler.h"
#include "pin_monitor.h"
#include "status_led.h"
#include "usb_comm.h"
#include "pico/stdlib.h"
#include <string.h>

/* Trigger state */
static uint8_t trigger_channel = 0;
static uint8_t trigger_mode = TRIGGER_NONE;
static uint16_t trigger_level = ADC_MAX_VALUE / 2;
static uint16_t last_adc_value = 0;
static bool triggered = false;
static bool osc_digital_enabled = true;

bool osc_mode_apply_trigger_config(const uint8_t *payload, uint16_t length) {
    uint16_t level;

    if (length < 4) {
        return false;
    }

    level = payload[2] | ((uint16_t)payload[3] << 8);

    if (payload[0] >= ADC_CHANNELS || payload[1] > TRIGGER_BOTH || level > ADC_MAX_VALUE) {
        return false;
    }

    trigger_channel = payload[0];
    trigger_mode = payload[1];
    trigger_level = level;
    triggered = false;
    last_adc_value = 0;
    return true;
}

bool osc_mode_apply_config(const uint8_t *payload, uint16_t length) {
    if (length < 1) {
        return false;
    }

    switch (payload[0]) {
    case CFG_OSC_ADC_DIVIDER:
        if (length == 2) {
            break;
        }

        if (length < 3) {
            return false;
        }

        adc_sampler_set_divider(payload[1] | ((uint16_t)payload[2] << 8));
        return true;

    case CFG_OSC_DIGITAL_ENABLE: {
        if (length == 2) {
            break;
        }

        if (length < 3) {
            return false;
        }

        bool enable = payload[1] != 0;

        if (enable != osc_digital_enabled) {
            osc_digital_enabled = enable;

            if (adc_sampler_is_running()) {
                if (osc_digital_enabled) {
                    pin_monitor_start();
                } else if (pin_monitor_is_running()) {
                    pin_monitor_stop();
                }
            }
        }

        return true;
    }

    case CFG_OSC_PIN_DIVIDER: {
        if (length < (uint16_t)(1 + sizeof(float))) {
            return false;
        }

        float divider;
        memcpy(&divider, &payload[1], sizeof(float));
        pin_monitor_set_divider(divider);
        return true;
    }

    default:
        break;
    }

    if (length == 2) {
        uint16_t divider = payload[0] | ((uint16_t)payload[1] << 8);
        adc_sampler_set_divider(divider);
        return true;
    }

    return false;
}

static bool check_trigger(uint16_t value) {
    if (trigger_mode == TRIGGER_NONE) {
        return true; /* Always pass */
    }

    bool trig = false;

    switch (trigger_mode) {
    case TRIGGER_RISING:
        trig = (last_adc_value < trigger_level && value >= trigger_level);
        break;
    case TRIGGER_FALLING:
        trig = (last_adc_value >= trigger_level && value < trigger_level);
        break;
    case TRIGGER_BOTH:
        trig = ((last_adc_value < trigger_level && value >= trigger_level) ||
                (last_adc_value >= trigger_level && value < trigger_level));
        break;
    }

    last_adc_value = value;
    return trig;
}

void osc_mode_init(void) {
    /* All 4 ADC channels enabled */
    adc_sampler_init(0x0F);

    /* Digital channels: GPIO0-22 */
    pin_monitor_init(OSC_DIGITAL_MASK);

    triggered = false;
    last_adc_value = 0;
}

int osc_mode_run(void) {
    uint16_t adc_buf[ADC_BUFFER_SIZE];
    uint32_t pin_buf[PIN_BUFFER_SIZE];
    uint8_t cmd_buf[PROTO_MAX_COMMAND_PAYLOAD];
    uint8_t cmd_type;
    uint16_t cmd_len;

    adc_sampler_start();
    if (osc_digital_enabled) {
        pin_monitor_start();
    }

    while (true) {
        usb_comm_task();
        status_led_update();

        /* Check for commands */
        if (usb_comm_receive_command(&cmd_type, cmd_buf, &cmd_len, sizeof(cmd_buf))) {
            switch (cmd_type) {
            case CMD_STOP:
                adc_sampler_stop();
                pin_monitor_stop();
                usb_comm_send_status(STATUS_OK);
                return -1;

            case CMD_MODE:
                adc_sampler_stop();
                pin_monitor_stop();
                if (cmd_len >= 1 && cmd_buf[0] <= MODE_OSCILLOSCOPE) {
                    usb_comm_send_status(STATUS_OK);
                    return cmd_buf[0];
                }
                usb_comm_send_error(STATUS_ERROR, "Invalid mode");
                return -1;

            case CMD_TRIGGER:
                if (osc_mode_apply_trigger_config(cmd_buf, cmd_len)) {
                    usb_comm_send_status(STATUS_OK);
                } else {
                    usb_comm_send_error(STATUS_ERROR, "Invalid trigger configuration");
                }
                break;

            case CMD_CONFIG:
                if (osc_mode_apply_config(cmd_buf, cmd_len)) {
                    usb_comm_send_status(STATUS_OK);
                } else {
                    usb_comm_send_error(STATUS_ERROR, "Invalid oscilloscope configuration");
                }
                break;

            default:
                break;
            }
        }

        /* Stream ADC data */
        uint64_t adc_start_time_ps;
        uint64_t adc_interval_ps;
        uint32_t adc_count = adc_sampler_read(adc_buf,
                                              ADC_BUFFER_SIZE,
                                              &adc_start_time_ps,
                                              &adc_interval_ps);
        if (adc_count > 0) {
            /* Check trigger if configured */
            if (trigger_mode != TRIGGER_NONE && !triggered) {
                uint8_t num_ch = adc_sampler_channel_count();
                for (uint32_t i = trigger_channel; i < adc_count; i += num_ch) {
                    if (check_trigger(adc_buf[i])) {
                        triggered = true;
                        /* Send trigger notification */
                        uint8_t trig_payload[4];
                        trig_payload[0] = trigger_channel;
                        trig_payload[1] = trigger_mode;
                        trig_payload[2] = (uint8_t)(adc_buf[i] & 0xFF);
                        trig_payload[3] = (uint8_t)((adc_buf[i] >> 8) & 0xFF);
                        usb_comm_send_frame(MSG_TRIGGER, trig_payload, 4);
                        break;
                    }
                }
            }

            usb_comm_send_adc_batches(adc_start_time_ps,
                                      adc_interval_ps,
                                      adc_sampler_channel_count(),
                                      adc_buf,
                                      adc_count);
        }

        uint32_t adc_overrun_count = adc_sampler_take_overrun_count();
        if (adc_overrun_count > 0) {
            usb_comm_send_overflow_report("ADC",
                                          adc_overrun_count,
                                          adc_overrun_count * ADC_BUFFER_SIZE);
            status_led_signal_overflow();
        }

        /* Stream digital pin data */
        uint64_t pin_start_time_ps;
        uint64_t pin_interval_ps;
        uint32_t pin_count = 0;

        if (osc_digital_enabled && pin_monitor_is_running()) {
            pin_count = pin_monitor_read(pin_buf,
                                         PIN_BUFFER_SIZE,
                                         &pin_start_time_ps,
                                         &pin_interval_ps);
        }

        if (pin_count > 0) {
            usb_comm_send_pin_batches(pin_start_time_ps,
                                      pin_interval_ps,
                                      OSC_DIGITAL_MASK,
                                      pin_buf,
                                      pin_count);
        }

        uint32_t pin_overrun_count = pin_monitor_take_overrun_count();
        if (pin_overrun_count > 0) {
            usb_comm_send_overflow_report("Pin",
                                          pin_overrun_count,
                                          pin_overrun_count * PIN_BUFFER_SIZE);
            status_led_signal_overflow();
        }

    }

    return -1;
}

void osc_mode_stop(void) {
    adc_sampler_stop();
    pin_monitor_stop();
}
