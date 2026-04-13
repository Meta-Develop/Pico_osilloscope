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
#include "usb_comm.h"
#include "pico/stdlib.h"

void hat_mode_init(void) {
    pin_monitor_init(HAT_DIGITAL_MASK);
}

int hat_mode_run(void) {
    uint32_t snapshot_buf[PIN_BUFFER_SIZE];
    uint8_t cmd_buf[PROTO_MAX_PAYLOAD];
    uint8_t cmd_type;
    uint16_t cmd_len;

    pin_monitor_start();
    usb_comm_send_status(STATUS_OK);

    while (true) {
        /* Check for commands */
        if (usb_comm_receive_command(&cmd_type, cmd_buf, &cmd_len, sizeof(cmd_buf))) {
            switch (cmd_type) {
            case CMD_STOP:
                pin_monitor_stop();
                usb_comm_send_status(STATUS_OK);
                return -1;

            case CMD_MODE:
                pin_monitor_stop();
                if (cmd_len >= 1) {
                    usb_comm_send_status(STATUS_OK);
                    return cmd_buf[0];
                }
                usb_comm_send_status(STATUS_OK);
                return -1;

            case CMD_CONFIG:
                /* Runtime clock divider config */
                if (cmd_len >= 4) {
                    float divider;
                    memcpy(&divider, cmd_buf, sizeof(float));
                    pin_monitor_set_divider(divider);
                    usb_comm_send_status(STATUS_OK);
                }
                break;

            default:
                break;
            }
        }

        /* Stream pin data when available */
        uint32_t count = pin_monitor_read(snapshot_buf, PIN_BUFFER_SIZE);
        if (count > 0) {
            /* Send as PIN_DATA frames
             * Each snapshot is 4 bytes (uint32_t).
             * Pack multiple snapshots per frame up to max payload. */
            uint32_t bytes_total = count * sizeof(uint32_t);
            uint32_t offset = 0;

            while (offset < bytes_total) {
                uint16_t chunk = (uint16_t)((bytes_total - offset > PROTO_MAX_PAYLOAD)
                                            ? PROTO_MAX_PAYLOAD
                                            : (bytes_total - offset));
                usb_comm_send_frame(MSG_PIN_DATA,
                                    (const uint8_t *)snapshot_buf + offset,
                                    chunk);
                offset += chunk;
            }
        }

        tud_task(); /* TinyUSB device task */
    }
}

void hat_mode_stop(void) {
    pin_monitor_stop();
}
