#include "usb_comm.h"
#include "config.h"

#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "tusb.h"

/* --- CRC-8 MAXIM --- */
uint8_t crc8_maxim(const uint8_t *data, uint32_t len) {
    uint8_t crc = 0x00;
    for (uint32_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 0x01) {
                crc = (crc >> 1) ^ 0x8C;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc;
}

/* --- TX --- */

static uint8_t tx_frame[5 + PROTO_MAX_PAYLOAD]; /* SYNC + TYPE + LEN(2) + PAYLOAD + CRC */

void usb_comm_init(void) {
    stdio_init_all();
}

bool usb_comm_send(uint8_t msg_type, const uint8_t *payload, uint16_t len) {
    if (len > PROTO_MAX_PAYLOAD) return false;
    if (!tud_cdc_connected()) return false;

    uint32_t frame_len = 0;
    tx_frame[frame_len++] = PROTO_SYNC_BYTE;
    tx_frame[frame_len++] = msg_type;
    tx_frame[frame_len++] = (uint8_t)(len & 0xFF);        /* length low byte */
    tx_frame[frame_len++] = (uint8_t)((len >> 8) & 0xFF); /* length high byte */

    if (len > 0 && payload != NULL) {
        memcpy(&tx_frame[frame_len], payload, len);
        frame_len += len;
    }

    /* CRC over type + length + payload */
    uint8_t crc = crc8_maxim(&tx_frame[1], frame_len - 1);
    tx_frame[frame_len++] = crc;

    /* Write to USB CDC */
    uint32_t written = 0;
    while (written < frame_len) {
        uint32_t avail = tud_cdc_write_available();
        if (avail == 0) {
            tud_cdc_write_flush();
            continue;
        }
        uint32_t chunk = frame_len - written;
        if (chunk > avail) chunk = avail;
        tud_cdc_write(&tx_frame[written], chunk);
        written += chunk;
    }
    tud_cdc_write_flush();
    return true;
}

/* --- RX --- */

typedef enum {
    RX_WAIT_SYNC,
    RX_READ_TYPE,
    RX_READ_LEN_LOW,
    RX_READ_LEN_HIGH,
    RX_READ_PAYLOAD,
    RX_READ_CRC
} rx_state_t;

static rx_state_t rx_state = RX_WAIT_SYNC;
static uint8_t rx_buf[USB_RX_BUF_SIZE];
static uint8_t rx_type = 0;
static uint16_t rx_expected_len = 0;
static uint16_t rx_payload_idx = 0;
static uint8_t rx_crc_byte = 0;

static uint8_t cmd_buf[USB_RX_BUF_SIZE];
static uint16_t cmd_len = 0;
static uint8_t cmd_type = 0;
static volatile bool cmd_ready = false;

static void rx_process_byte(uint8_t byte) {
    switch (rx_state) {
    case RX_WAIT_SYNC:
        if (byte == PROTO_SYNC_BYTE) rx_state = RX_READ_TYPE;
        break;
    case RX_READ_TYPE:
        rx_type = byte;
        rx_state = RX_READ_LEN_LOW;
        break;
    case RX_READ_LEN_LOW:
        rx_expected_len = byte;
        rx_state = RX_READ_LEN_HIGH;
        break;
    case RX_READ_LEN_HIGH:
        rx_expected_len |= ((uint16_t)byte << 8);
        rx_payload_idx = 0;
        if (rx_expected_len == 0) {
            rx_state = RX_READ_CRC;
        } else if (rx_expected_len > USB_RX_BUF_SIZE) {
            rx_state = RX_WAIT_SYNC; /* frame too large, discard */
        } else {
            rx_state = RX_READ_PAYLOAD;
        }
        break;
    case RX_READ_PAYLOAD:
        rx_buf[rx_payload_idx++] = byte;
        if (rx_payload_idx >= rx_expected_len) {
            rx_state = RX_READ_CRC;
        }
        break;
    case RX_READ_CRC:
        rx_crc_byte = byte;
        /* Verify CRC: compute over type + len(2) + payload */
        {
            uint8_t verify_buf[3 + USB_RX_BUF_SIZE];
            verify_buf[0] = rx_type;
            verify_buf[1] = (uint8_t)(rx_expected_len & 0xFF);
            verify_buf[2] = (uint8_t)((rx_expected_len >> 8) & 0xFF);
            if (rx_expected_len > 0) {
                memcpy(&verify_buf[3], rx_buf, rx_expected_len);
            }
            uint8_t expected_crc = crc8_maxim(verify_buf, 3 + rx_expected_len);
            if (rx_crc_byte == expected_crc && !cmd_ready) {
                cmd_type = rx_type;
                cmd_len = rx_expected_len;
                if (cmd_len > 0) {
                    memcpy(cmd_buf, rx_buf, cmd_len);
                }
                cmd_ready = true;
            }
        }
        rx_state = RX_WAIT_SYNC;
        break;
    }
}

void usb_comm_poll(void) {
    tud_task();
    if (!tud_cdc_available()) return;

    uint8_t buf[64];
    uint32_t count = tud_cdc_read(buf, sizeof(buf));
    for (uint32_t i = 0; i < count; i++) {
        rx_process_byte(buf[i]);
    }
}

bool usb_comm_cmd_available(void) {
    return cmd_ready;
}

uint8_t usb_comm_read_cmd(uint8_t *buf, uint16_t *out_len, uint16_t buf_size) {
    if (!cmd_ready) {
        *out_len = 0;
        return 0;
    }

    uint8_t type = cmd_type;
    uint16_t len = cmd_len;
    if (len > buf_size) len = buf_size;
    if (len > 0) {
        memcpy(buf, cmd_buf, len);
    }
    *out_len = len;
    cmd_ready = false;
    return type;
}
