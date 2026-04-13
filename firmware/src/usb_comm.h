/**
 * usb_comm.h — USB CDC Serial Communication
 *
 * Binary protocol framing for Pico <-> PC communication.
 */

#ifndef USB_COMM_H
#define USB_COMM_H

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize USB CDC serial interface.
 * Calls stdio_init_all() and waits for connection.
 */
void usb_comm_init(void);

/**
 * Send a protocol frame over USB.
 *
 * Frame format: SYNC(0xAA) | TYPE(1B) | LENGTH(2B LE) | PAYLOAD(N) | CRC8(1B)
 *
 * @param type    Message type (MSG_PIN_DATA, MSG_ADC_DATA, etc.)
 * @param payload Payload data
 * @param length  Payload length in bytes
 * @return true on success
 */
bool usb_comm_send_frame(uint8_t type, const uint8_t *payload, uint16_t length);

/**
 * Send a status response.
 *
 * @param status_code STATUS_OK, STATUS_BUSY, etc.
 */
void usb_comm_send_status(uint8_t status_code);

/**
 * Send an error response with message.
 *
 * @param error_code Error identifier
 * @param message    Human-readable error string (null-terminated)
 */
void usb_comm_send_error(uint8_t error_code, const char *message);

/**
 * Check for and parse an incoming command frame.
 * Non-blocking: returns false if no complete frame available.
 *
 * @param type    Output: command type
 * @param payload Output: payload buffer (caller provides)
 * @param length  Output: payload length
 * @param max_len Maximum payload buffer size
 * @return true if a complete command was received
 */
bool usb_comm_receive_command(uint8_t *type, uint8_t *payload,
                              uint16_t *length, uint16_t max_len);

/**
 * Compute CRC-8 MAXIM over a data buffer.
 *
 * @param data   Data buffer
 * @param length Data length
 * @return CRC-8 value
 */
uint8_t crc8_maxim(const uint8_t *data, uint16_t length);

/**
 * Check if USB is connected and ready.
 *
 * @return true if connected
 */
bool usb_comm_connected(void);

#endif /* USB_COMM_H */
