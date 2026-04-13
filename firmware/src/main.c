/**
 * main.c — Pico Oscilloscope Entry Point
 *
 * Initializes hardware and runs the selected operating mode.
 * Default mode: Hat Mode (all-digital GPIO monitoring).
 */

#include "config.h"
#include "usb_comm.h"
#include "hat_mode.h"
#include "osc_mode.h"
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "tusb.h"

static uint8_t current_mode = MODE_HAT;

static void led_init(void) {
    gpio_init(GPIO_LED);
    gpio_set_dir(GPIO_LED, GPIO_OUT);
    gpio_put(GPIO_LED, 0);
}

static void led_set(bool on) {
    gpio_put(GPIO_LED, on);
}

static void wait_for_usb(void) {
    /* Blink LED while waiting for USB connection */
    bool led_state = false;
    while (!tud_cdc_connected()) {
        tud_task();
        led_state = !led_state;
        led_set(led_state);
        sleep_ms(LED_BLINK_MS);
    }
    led_set(true);
}

static void handle_idle_commands(void) {
    uint8_t cmd_buf[PROTO_MAX_PAYLOAD];
    uint8_t cmd_type;
    uint16_t cmd_len;

    /* Process commands while not in a mode */
    while (usb_comm_receive_command(&cmd_type, cmd_buf, &cmd_len, sizeof(cmd_buf))) {
        switch (cmd_type) {
        case CMD_MODE:
            if (cmd_len >= 1) {
                current_mode = cmd_buf[0];
                usb_comm_send_status(STATUS_OK);
            }
            break;

        case CMD_START:
            usb_comm_send_status(STATUS_OK);
            return; /* Exit idle loop to start mode */

        default:
            usb_comm_send_status(STATUS_OK);
            break;
        }
    }
}

int main(void) {
    /* Initialize core peripherals */
    led_init();
    usb_comm_init();

    /* Wait for USB host connection */
    wait_for_usb();

    while (true) {
        int next_mode;

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

        /* Handle mode switch or stop */
        if (next_mode >= 0) {
            current_mode = (uint8_t)next_mode;
        } else {
            /* Stopped: wait for new command */
            led_set(true);
            while (true) {
                tud_task();
                handle_idle_commands();
                if (usb_comm_connected()) {
                    /* Check if start command was processed */
                    break;
                }
                sleep_ms(USB_POLL_MS);
            }
        }
    }

    return 0;
}
