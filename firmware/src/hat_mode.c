/**
 * hat_mode.c — Hat Mode: All-Digital GPIO Monitoring
 *
 * All GPIO pins (GPIO0-22, GPIO25-29) are read as digital logic.
 * GPIO26-29 are explicitly NOT used as ADC in this mode.
 * PIO provides high-speed parallel sampling into DMA buffers.
 */

#include "hat_mode.h"
#include "config.h"
#include "pin_monitor.h"
#include "status_led.h"
#include "usb_comm.h"
#include "pico/stdlib.h"
#include <string.h>

bool hat_mode_apply_config(const uint8_t *payload, uint16_t length) {
    if (length == sizeof(float)) {
        float divider;
        memcpy(&divider, payload, sizeof(float));
        pin_monitor_set_divider(divider);
        return true;
    }

    if (length >= 1 && payload[0] == CFG_HAT_PIN_DIVIDER &&
        length >= (uint16_t)(1 + sizeof(float))) {
        float divider;
        memcpy(&divider, &payload[1], sizeof(float));
        pin_monitor_set_divider(divider);
        return true;
    }

    return false;
}

void hat_mode_init(void) {
    pin_monitor_init(HAT_DIGITAL_MASK);
}

int hat_mode_run(void) {
    uint32_t snapshot_buf[PIN_BUFFER_SIZE];
    uint8_t cmd_buf[PROTO_MAX_COMMAND_PAYLOAD];
    uint8_t cmd_type;
    uint16_t cmd_len;

    pin_monitor_start();

    while (true) {
        usb_comm_task();
        status_led_update();

        /* Check for commands */
        if (usb_comm_receive_command(&cmd_type, cmd_buf, &cmd_len, sizeof(cmd_buf))) {
            switch (cmd_type) {
            case CMD_STOP:
                pin_monitor_stop();
                usb_comm_send_status(STATUS_OK);
                return -1;

            case CMD_MODE:
                pin_monitor_stop();
                if (cmd_len >= 1 && cmd_buf[0] <= MODE_OSCILLOSCOPE) {
                    usb_comm_send_status(STATUS_OK);
                    return cmd_buf[0];
                }
                usb_comm_send_error(STATUS_ERROR, "Invalid mode");
                return -1;

            case CMD_CONFIG:
                if (hat_mode_apply_config(cmd_buf, cmd_len)) {
                    usb_comm_send_status(STATUS_OK);
                } else {
                    usb_comm_send_error(STATUS_ERROR, "Invalid hat configuration");
                }
                break;

            default:
                break;
            }
        }

        /* Stream pin data when available */
        uint64_t start_time_ps;
        uint64_t sample_interval_ps;
        uint32_t count = pin_monitor_read(snapshot_buf,
                                          PIN_BUFFER_SIZE,
                                          &start_time_ps,
                                          &sample_interval_ps);
        if (count > 0) {
            usb_comm_send_pin_batches(start_time_ps,
                                      sample_interval_ps,
                                      HAT_DIGITAL_MASK,
                                      snapshot_buf,
                                      count);
        }

        uint32_t overrun_count = pin_monitor_take_overrun_count();
        if (overrun_count > 0) {
            usb_comm_send_overflow_report("Pin",
                                          overrun_count,
                                          overrun_count * PIN_BUFFER_SIZE);
            status_led_signal_overflow();
        }

    }

    return -1;
}

void hat_mode_stop(void) {
    pin_monitor_stop();
}
