/**
 * usb_comm.c — USB CDC Serial Communication
 *
 * Binary protocol implementation for Pico <-> PC data exchange.
 */

#include "usb_comm.h"
#include "config.h"
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include <string.h>

/* Receive state machine */
typedef enum {
    RX_WAIT_SYNC,
    RX_WAIT_TYPE,
    RX_WAIT_LEN_LO,
    RX_WAIT_LEN_HI,
    RX_WAIT_PAYLOAD,
    RX_WAIT_CRC
} rx_state_t;

static rx_state_t rx_state = RX_WAIT_SYNC;
static uint8_t rx_type;
static uint16_t rx_length;
static uint16_t rx_received;
static uint8_t rx_buf[PROTO_MAX_PAYLOAD];

static uint8_t crc8_maxim_update(uint8_t crc, uint8_t byte) {
    crc ^= byte;
    for (uint8_t bit = 0; bit < 8; bit++) {
        if (crc & 0x80) {
            crc = (uint8_t)((crc << 1) ^ CRC8_POLY);
        } else {
            crc <<= 1;
        }
    }
    return crc;
}

static uint8_t frame_crc(uint8_t type, uint16_t length, const uint8_t *payload) {
    uint8_t crc = CRC8_INIT;

    crc = crc8_maxim_update(crc, type);
    crc = crc8_maxim_update(crc, (uint8_t)(length & 0xFF));
    crc = crc8_maxim_update(crc, (uint8_t)((length >> 8) & 0xFF));

    for (uint16_t i = 0; i < length; i++) {
        crc = crc8_maxim_update(crc, payload[i]);
    }

    return crc;
}

static bool usb_comm_write_all(const uint8_t *data, uint32_t length) {
    if (!stdio_usb_connected()) {
        return false;
    }

    for (uint32_t i = 0; i < length; i++) {
        if (putchar_raw(data[i]) == PICO_ERROR_TIMEOUT) {
            return false;
        }
    }

    stdio_flush();

    return true;
}

void usb_comm_init(void) {
    stdio_init_all();
}

uint8_t crc8_maxim(const uint8_t *data, uint16_t length) {
    uint8_t crc = CRC8_INIT;
    for (uint16_t i = 0; i < length; i++) {
        crc = crc8_maxim_update(crc, data[i]);
    }
    return crc;
}

bool usb_comm_connected(void) {
    return stdio_usb_connected();
}

bool usb_comm_send_frame(uint8_t type, const uint8_t *payload, uint16_t length) {
    if (!stdio_usb_connected()) {
        return false;
    }

    if (length > 0 && payload == NULL) {
        return false;
    }

    uint8_t header[PROTO_HEADER_SIZE];
    header[0] = PROTO_SYNC;
    header[1] = type;
    header[2] = (uint8_t)(length & 0xFF);
    header[3] = (uint8_t)((length >> 8) & 0xFF);

    uint8_t crc = frame_crc(type, length, payload);

    if (!usb_comm_write_all(header, PROTO_HEADER_SIZE)) {
        return false;
    }

    if (length > 0 && payload != NULL && !usb_comm_write_all(payload, length)) {
        return false;
    }

    return usb_comm_write_all(&crc, PROTO_CRC_SIZE);
}

void usb_comm_send_status(uint8_t status_code) {
    usb_comm_send_frame(MSG_STATUS, &status_code, 1);
}

void usb_comm_send_error(uint8_t error_code, const char *message) {
    uint16_t msg_len = (uint16_t)strlen(message);
    uint16_t total = 1 + msg_len;
    uint8_t buf[PROTO_MAX_PAYLOAD];

    if (total > PROTO_MAX_PAYLOAD) {
        total = PROTO_MAX_PAYLOAD;
        msg_len = total - 1;
    }

    buf[0] = error_code;
    memcpy(&buf[1], message, msg_len);

    usb_comm_send_frame(MSG_ERROR, buf, total);
}

bool usb_comm_receive_command(uint8_t *type, uint8_t *payload,
                              uint16_t *length, uint16_t max_len) {
    int ch;

    while ((ch = getchar_timeout_us(0)) != PICO_ERROR_TIMEOUT) {
        uint8_t byte = (uint8_t)ch;

        switch (rx_state) {
        case RX_WAIT_SYNC:
            if (byte == PROTO_SYNC) {
                rx_state = RX_WAIT_TYPE;
            }
            break;

        case RX_WAIT_TYPE:
            rx_type = byte;
            rx_state = RX_WAIT_LEN_LO;
            break;

        case RX_WAIT_LEN_LO:
            rx_length = byte;
            rx_state = RX_WAIT_LEN_HI;
            break;

        case RX_WAIT_LEN_HI:
            rx_length |= ((uint16_t)byte << 8);
            if (rx_length > PROTO_MAX_PAYLOAD || rx_length > max_len) {
                rx_state = RX_WAIT_SYNC; /* Frame too large, discard */
                break;
            }
            if (rx_length == 0) {
                rx_state = RX_WAIT_CRC;
            } else {
                rx_received = 0;
                rx_state = RX_WAIT_PAYLOAD;
            }
            break;

        case RX_WAIT_PAYLOAD:
            rx_buf[rx_received++] = byte;
            if (rx_received >= rx_length) {
                rx_state = RX_WAIT_CRC;
            }
            break;

        case RX_WAIT_CRC: {
            /* Verify CRC */
            uint8_t expected_crc = frame_crc(rx_type, rx_length, rx_buf);

            rx_state = RX_WAIT_SYNC;

            if (byte == expected_crc) {
                *type = rx_type;
                *length = rx_length;
                if (rx_length > 0) {
                    memcpy(payload, rx_buf, rx_length);
                }
                return true;
            }
            /* CRC mismatch, frame discarded */
            break;
        }
        }
    }

    return false;
}
