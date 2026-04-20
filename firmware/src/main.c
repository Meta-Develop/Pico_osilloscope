/**
 * main.c — Pico Oscilloscope Entry Point
 *
 * Initializes hardware and runs the selected operating mode.
 * Default mode: Hat Mode (all-digital GPIO monitoring).
 */

#include "config.h"
#include "clock_manager.h"
#include "status_led.h"
#include "usb_comm.h"
#include "hat_mode.h"
#include "osc_mode.h"
#include "pico/stdlib.h"

static uint8_t current_mode = MODE_HAT;
static bool sampling_requested = false;

static void wait_for_usb(void) {
    status_led_set_state(STATUS_LED_WAITING_USB);

    while (!usb_comm_connected()) {
        usb_comm_task();
        status_led_update();
        sleep_ms(USB_POLL_MS);
    }
}

static void handle_idle_commands(void) {
    uint8_t cmd_buf[PROTO_MAX_COMMAND_PAYLOAD];
    uint8_t cmd_type;
    uint16_t cmd_len;

    while (usb_comm_receive_command(&cmd_type, cmd_buf, &cmd_len, sizeof(cmd_buf))) {
        switch (cmd_type) {
        case CMD_MODE:
            if (cmd_len >= 1 && cmd_buf[0] <= MODE_OSCILLOSCOPE) {
                current_mode = cmd_buf[0];
                usb_comm_send_status(STATUS_OK);
            } else {
                usb_comm_send_error(STATUS_ERROR, "Invalid mode");
            }
            break;

        case CMD_START:
            sampling_requested = true;
            usb_comm_send_status(STATUS_OK);
            return;

        case CMD_STOP:
            sampling_requested = false;
            usb_comm_send_status(STATUS_OK);
            break;

        case CMD_CONFIG:
            if (current_mode == MODE_HAT) {
                if (hat_mode_apply_config(cmd_buf, cmd_len)) {
                    usb_comm_send_status(STATUS_OK);
                } else {
                    usb_comm_send_error(STATUS_ERROR, "Invalid hat configuration");
                }
            } else if (current_mode == MODE_OSCILLOSCOPE) {
                if (osc_mode_apply_config(cmd_buf, cmd_len)) {
                    usb_comm_send_status(STATUS_OK);
                } else {
                    usb_comm_send_error(STATUS_ERROR, "Invalid oscilloscope configuration");
                }
            } else {
                usb_comm_send_error(STATUS_ERROR, "Configuration unavailable");
            }
            break;

        case CMD_TRIGGER:
            if (current_mode == MODE_OSCILLOSCOPE) {
                if (osc_mode_apply_trigger_config(cmd_buf, cmd_len)) {
                    usb_comm_send_status(STATUS_OK);
                } else {
                    usb_comm_send_error(STATUS_ERROR, "Invalid trigger configuration");
                }
            } else {
                usb_comm_send_error(STATUS_ERROR, "Trigger only supported in oscilloscope mode");
            }
            break;

        default:
            usb_comm_send_error(STATUS_ERROR, "Unsupported idle command");
            break;
        }
    }
}

int main(void) {
    /* Initialize core peripherals */
    status_led_init();
    clock_manager_init();
    usb_comm_init();

    /* Wait for USB host connection */
    wait_for_usb();

    while (true) {
        int next_mode;

        usb_comm_task();

        if (!sampling_requested) {
            status_led_set_state(
                current_mode == MODE_OSCILLOSCOPE ? STATUS_LED_IDLE_OSC : STATUS_LED_IDLE_HAT
            );
            handle_idle_commands();
            status_led_update();
            sleep_ms(USB_POLL_MS);
            continue;
        }

        status_led_set_state(
            current_mode == MODE_OSCILLOSCOPE ? STATUS_LED_ACTIVE_OSC : STATUS_LED_ACTIVE_HAT
        );

        switch (current_mode) {
        case MODE_HAT:
            hat_mode_init();
            next_mode = hat_mode_run();
            hat_mode_stop();
            break;

        case MODE_OSCILLOSCOPE:
            osc_mode_init();
            next_mode = osc_mode_run();
            osc_mode_stop();
            break;

        default:
            current_mode = MODE_HAT;
            continue;
        }

        sampling_requested = false;

        if (next_mode >= 0) {
            current_mode = (uint8_t)next_mode;
        }
    }

    return 0;
}
