#include <stdio.h>
#include "pico/stdlib.h"
#include "hardware/gpio.h"

#include "config.h"
#include "usb_comm.h"
#include "hat_mode.h"

static uint8_t current_mode = DEFAULT_MODE;

static void led_init(void) {
    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);
    gpio_put(LED_PIN, 0);
}

static void led_toggle(void) {
    gpio_xor_mask(1u << LED_PIN);
}

static void handle_command(void) {
    uint8_t buf[USB_RX_BUF_SIZE];
    uint16_t len = 0;
    uint8_t type = usb_comm_read_cmd(buf, &len, sizeof(buf));

    switch (type) {
    case CMD_START:
        if (current_mode == MODE_HAT) {
            hat_mode_start();
        }
        break;

    case CMD_STOP:
        if (current_mode == MODE_HAT) {
            hat_mode_stop();
        }
        break;

    case CMD_MODE:
        if (len >= 1) {
            uint8_t new_mode = buf[0];
            if (new_mode != current_mode) {
                /* Stop current mode */
                if (current_mode == MODE_HAT) hat_mode_stop();

                current_mode = new_mode;

                /* Send status acknowledgement */
                uint8_t status = current_mode;
                usb_comm_send(MSG_STATUS, &status, 1);
            }
        }
        break;

    case CMD_CONFIG:
        /* Configuration commands - extensible */
        break;

    default:
        break;
    }
}

int main(void) {
    /* Initialize USB CDC */
    usb_comm_init();

    /* LED for status */
    led_init();

    /* Print startup message */
    printf("Pico Oscilloscope v%d.%d.%d\n",
           FIRMWARE_VERSION_MAJOR,
           FIRMWARE_VERSION_MINOR,
           FIRMWARE_VERSION_PATCH);
    printf("Mode: %s\n",
           current_mode == MODE_HAT ? "Hat" : "Oscilloscope");

    /* Initialize default mode */
    if (current_mode == MODE_HAT) {
        hat_mode_init();
    }

    uint32_t led_counter = 0;

    /* Main loop */
    while (true) {
        /* Poll USB for incoming commands */
        usb_comm_poll();

        /* Handle received commands */
        if (usb_comm_cmd_available()) {
            handle_command();
        }

        /* Run active mode */
        if (current_mode == MODE_HAT) {
            hat_mode_tick();
        }

        /* Blink LED as heartbeat */
        if (++led_counter >= 100000) {
            led_toggle();
            led_counter = 0;
        }
    }

    return 0;
}
