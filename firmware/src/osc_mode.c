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
#include "usb_comm.h"
#include "pico/stdlib.h"
#include <string.h>

/* Trigger state */
static uint8_t trigger_channel = 0;
static uint8_t trigger_mode = TRIGGER_NONE;
static uint16_t trigger_level = ADC_MAX_VALUE / 2;
static uint16_t last_adc_value = 0;
static bool triggered = false;

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
    uint8_t cmd_buf[PROTO_MAX_PAYLOAD];
    uint8_t cmd_type;
    uint16_t cmd_len;

    adc_sampler_start();
    pin_monitor_start();
    usb_comm_send_status(STATUS_OK);

    while (true) {
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
                if (cmd_len >= 1) {
                    usb_comm_send_status(STATUS_OK);
                    return cmd_buf[0];
                }
                usb_comm_send_status(STATUS_OK);
                return -1;

            case CMD_TRIGGER:
                /* Trigger config: [channel(1) | mode(1) | level(2 LE)] */
                if (cmd_len >= 4) {
                    trigger_channel = cmd_buf[0];
                    trigger_mode = cmd_buf[1];
                    trigger_level = cmd_buf[2] | ((uint16_t)cmd_buf[3] << 8);
                    triggered = false;
                    usb_comm_send_status(STATUS_OK);
                }
                break;

            case CMD_CONFIG:
                /* ADC divider config */
                if (cmd_len >= 2) {
                    uint16_t div = cmd_buf[0] | ((uint16_t)cmd_buf[1] << 8);
                    adc_sampler_set_divider(div);
                    usb_comm_send_status(STATUS_OK);
                }
                break;

            default:
                break;
            }
        }

        /* Stream ADC data */
        uint32_t adc_count = adc_sampler_read(adc_buf, ADC_BUFFER_SIZE);
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

            /* Send ADC data */
            uint32_t bytes = adc_count * sizeof(uint16_t);
            uint32_t offset = 0;
            while (offset < bytes) {
                uint16_t chunk = (uint16_t)((bytes - offset > PROTO_MAX_PAYLOAD)
                                            ? PROTO_MAX_PAYLOAD
                                            : (bytes - offset));
                usb_comm_send_frame(MSG_ADC_DATA,
                                    (const uint8_t *)adc_buf + offset,
                                    chunk);
                offset += chunk;
            }
        }

        /* Stream digital pin data */
        uint32_t pin_count = pin_monitor_read(pin_buf, PIN_BUFFER_SIZE);
        if (pin_count > 0) {
            uint32_t bytes = pin_count * sizeof(uint32_t);
            uint32_t offset = 0;
            while (offset < bytes) {
                uint16_t chunk = (uint16_t)((bytes - offset > PROTO_MAX_PAYLOAD)
                                            ? PROTO_MAX_PAYLOAD
                                            : (bytes - offset));
                usb_comm_send_frame(MSG_PIN_DATA,
                                    (const uint8_t *)pin_buf + offset,
                                    chunk);
                offset += chunk;
            }
        }

        tud_task();
    }
}

void osc_mode_stop(void) {
    adc_sampler_stop();
    pin_monitor_stop();
}
