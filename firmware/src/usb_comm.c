/**
 * usb_comm.c — USB CDC Communication
 *
 * Binary protocol implementation for Pico <-> PC data exchange.
 */

#include "usb_comm.h"
#include "config.h"
#include "pico/stdio.h"
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include <stdio.h>
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
static uint8_t rx_buf[PROTO_MAX_COMMAND_PAYLOAD];
static uint8_t tx_buf[PROTO_MAX_PAYLOAD];

static void write_u16_le(uint8_t *buffer, uint16_t value) {
    buffer[0] = (uint8_t)(value & 0xFFu);
    buffer[1] = (uint8_t)((value >> 8) & 0xFFu);
}

static void write_u32_le(uint8_t *buffer, uint32_t value) {
    buffer[0] = (uint8_t)(value & 0xFFu);
    buffer[1] = (uint8_t)((value >> 8) & 0xFFu);
    buffer[2] = (uint8_t)((value >> 16) & 0xFFu);
    buffer[3] = (uint8_t)((value >> 24) & 0xFFu);
}

static void write_u64_le(uint8_t *buffer, uint64_t value) {
    for (uint8_t index = 0; index < 8; index++) {
        buffer[index] = (uint8_t)((value >> (index * 8u)) & 0xFFu);
    }
}

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
    if (length == 0) {
        return true;
    }

    if (!stdio_usb_connected()) {
        return false;
    }

    return stdio_put_string((const char *)data, (int)length, false, false) == (int)length;
}

static uint16_t build_adc_batch_payload(uint64_t start_time_ps,
                                        uint64_t sample_interval_ps,
                                        uint8_t channel_count,
                                        const uint16_t *samples,
                                        uint16_t sample_count) {
    uint32_t sample_bytes = (uint32_t)sample_count * sizeof(uint16_t);
    uint16_t payload_length = (uint16_t)(PROTO_ADC_BATCH_OVERHEAD + sample_bytes);

    if (payload_length > PROTO_MAX_PAYLOAD) {
        return 0;
    }

    write_u64_le(&tx_buf[0], start_time_ps);
    write_u64_le(&tx_buf[8], sample_interval_ps);
    write_u16_le(&tx_buf[16], sample_count);
    tx_buf[18] = channel_count;
    tx_buf[19] = 0;

    memcpy(&tx_buf[PROTO_ADC_BATCH_OVERHEAD], samples, sample_bytes);
    return payload_length;
}

static uint16_t build_pin_batch_payload(uint64_t start_time_ps,
                                        uint64_t sample_interval_ps,
                                        uint32_t pin_mask,
                                        const uint32_t *snapshots,
                                        uint16_t sample_count) {
    uint32_t sample_bytes = (uint32_t)sample_count * sizeof(uint32_t);
    uint16_t payload_length = (uint16_t)(PROTO_PIN_BATCH_OVERHEAD + sample_bytes);

    if (payload_length > PROTO_MAX_PAYLOAD) {
        return 0;
    }

    write_u64_le(&tx_buf[0], start_time_ps);
    write_u64_le(&tx_buf[8], sample_interval_ps);
    write_u16_le(&tx_buf[16], sample_count);
    write_u32_le(&tx_buf[18], pin_mask);
    write_u16_le(&tx_buf[22], 0);

    memcpy(&tx_buf[PROTO_PIN_BATCH_OVERHEAD], snapshots, sample_bytes);
    return payload_length;
}

void usb_comm_init(void) {
    stdio_init_all();
}

void usb_comm_task(void) {
    tight_loop_contents();
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
    if (length > PROTO_MAX_PAYLOAD) {
        return false;
    }

    if (!usb_comm_connected()) {
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

bool usb_comm_send_adc_batch(uint64_t start_time_ps,
                             uint64_t sample_interval_ps,
                             uint8_t channel_count,
                             const uint16_t *samples,
                             uint16_t sample_count) {
    uint16_t payload_length;

    if (sample_count == 0 || samples == NULL) {
        return false;
    }

    payload_length = build_adc_batch_payload(start_time_ps,
                                             sample_interval_ps,
                                             channel_count,
                                             samples,
                                             sample_count);
    if (payload_length == 0) {
        return false;
    }

    return usb_comm_send_frame(MSG_ADC_BATCH, tx_buf, payload_length);
}

bool usb_comm_send_adc_batches(uint64_t start_time_ps,
                               uint64_t sample_interval_ps,
                               uint8_t channel_count,
                               const uint16_t *samples,
                               uint32_t sample_count) {
    const uint16_t max_batch_samples =
        (PROTO_MAX_PAYLOAD - PROTO_ADC_BATCH_OVERHEAD) / sizeof(uint16_t);
    uint32_t offset = 0;
    bool success = true;

    if (sample_count == 0) {
        return true;
    }

    if (samples == NULL || max_batch_samples == 0) {
        return false;
    }

    while (offset < sample_count) {
        uint16_t chunk_count = (uint16_t)((sample_count - offset > max_batch_samples)
            ? max_batch_samples
            : (sample_count - offset));

        success = usb_comm_send_adc_batch(start_time_ps,
                                          sample_interval_ps,
                                          channel_count,
                                          &samples[offset],
                                          chunk_count) && success;

        start_time_ps += (uint64_t)chunk_count * sample_interval_ps;
        offset += chunk_count;
    }

    return success;
}

bool usb_comm_send_pin_batch(uint64_t start_time_ps,
                             uint64_t sample_interval_ps,
                             uint32_t pin_mask,
                             const uint32_t *snapshots,
                             uint16_t sample_count) {
    uint16_t payload_length;

    if (sample_count == 0 || snapshots == NULL) {
        return false;
    }

    payload_length = build_pin_batch_payload(start_time_ps,
                                             sample_interval_ps,
                                             pin_mask,
                                             snapshots,
                                             sample_count);
    if (payload_length == 0) {
        return false;
    }

    return usb_comm_send_frame(MSG_PIN_BATCH, tx_buf, payload_length);
}

bool usb_comm_send_pin_batches(uint64_t start_time_ps,
                               uint64_t sample_interval_ps,
                               uint32_t pin_mask,
                               const uint32_t *snapshots,
                               uint32_t sample_count) {
    const uint16_t max_batch_samples =
        (PROTO_MAX_PAYLOAD - PROTO_PIN_BATCH_OVERHEAD) / sizeof(uint32_t);
    uint32_t offset = 0;
    bool success = true;

    if (sample_count == 0) {
        return true;
    }

    if (snapshots == NULL || max_batch_samples == 0) {
        return false;
    }

    while (offset < sample_count) {
        uint16_t chunk_count = (uint16_t)((sample_count - offset > max_batch_samples)
            ? max_batch_samples
            : (sample_count - offset));

        success = usb_comm_send_pin_batch(start_time_ps,
                                          sample_interval_ps,
                                          pin_mask,
                                          &snapshots[offset],
                                          chunk_count) && success;

        start_time_ps += (uint64_t)chunk_count * sample_interval_ps;
        offset += chunk_count;
    }

    return success;
}

void usb_comm_send_status(uint8_t status_code) {
    usb_comm_send_frame(MSG_STATUS, &status_code, 1);
}

void usb_comm_send_error(uint8_t error_code, const char *message) {
    uint16_t msg_len = (uint16_t)strlen(message);
    uint16_t total = 1 + msg_len;

    if (total > PROTO_MAX_PAYLOAD) {
        total = PROTO_MAX_PAYLOAD;
        msg_len = total - 1;
    }

    tx_buf[0] = error_code;
    memcpy(&tx_buf[1], message, msg_len);

    usb_comm_send_frame(MSG_ERROR, tx_buf, total);
}

void usb_comm_send_overflow_report(const char *stream_name,
                                   uint32_t dropped_batches,
                                   uint32_t lost_samples) {
    char message[96];

    if (stream_name == NULL || dropped_batches == 0) {
        return;
    }

    snprintf(message,
             sizeof(message),
             "%s capture overflow dropped_batches=%lu lost_samples=%lu",
             stream_name,
             (unsigned long)dropped_batches,
             (unsigned long)lost_samples);
    usb_comm_send_error(STATUS_OVERFLOW, message);
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
            if (rx_length > PROTO_MAX_COMMAND_PAYLOAD || rx_length > max_len) {
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
