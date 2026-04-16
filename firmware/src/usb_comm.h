/**
 * usb_comm.h — USB CDC Communication
 *
 * Binary protocol framing for Pico <-> PC communication.
 */

#ifndef USB_COMM_H
#define USB_COMM_H

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize the stdio-managed USB CDC transport.
 */
void usb_comm_init(void);

/**
 * Service background USB communication work in long-running loops.
 */
void usb_comm_task(void);

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
 * Send a timestamped ADC sample batch.
 *
 * @param start_time_ps      Stream-relative timestamp of the first sample
 * @param sample_interval_ps Interval between interleaved ADC samples
 * @param channel_count      Number of active ADC channels
 * @param samples            ADC samples (interleaved by channel)
 * @param sample_count       Number of 16-bit samples in this batch
 * @return true on success
 */
bool usb_comm_send_adc_batch(uint64_t start_time_ps,
                             uint64_t sample_interval_ps,
                             uint8_t channel_count,
                             const uint16_t *samples,
                             uint16_t sample_count);

/**
 * Send one or more timestamped ADC sample batches.
 * Splits the sample stream into multiple protocol frames when needed.
 *
 * @param start_time_ps      Stream-relative timestamp of the first sample
 * @param sample_interval_ps Interval between interleaved ADC samples
 * @param channel_count      Number of active ADC channels
 * @param samples            ADC samples (interleaved by channel)
 * @param sample_count       Number of 16-bit samples to send
 * @return true if all frames were sent successfully
 */
bool usb_comm_send_adc_batches(uint64_t start_time_ps,
                               uint64_t sample_interval_ps,
                               uint8_t channel_count,
                               const uint16_t *samples,
                               uint32_t sample_count);

/**
 * Send a timestamped GPIO snapshot batch.
 *
 * @param start_time_ps      Stream-relative timestamp of the first snapshot
 * @param sample_interval_ps Interval between GPIO snapshots
 * @param pin_mask           Mask of valid GPIO bits in each snapshot
 * @param snapshots          GPIO snapshots
 * @param sample_count       Number of 32-bit snapshots in this batch
 * @return true on success
 */
bool usb_comm_send_pin_batch(uint64_t start_time_ps,
                             uint64_t sample_interval_ps,
                             uint32_t pin_mask,
                             const uint32_t *snapshots,
                             uint16_t sample_count);

/**
 * Send one or more timestamped GPIO snapshot batches.
 * Splits the snapshot stream into multiple protocol frames when needed.
 *
 * @param start_time_ps      Stream-relative timestamp of the first snapshot
 * @param sample_interval_ps Interval between GPIO snapshots
 * @param pin_mask           Mask of valid GPIO bits in each snapshot
 * @param snapshots          GPIO snapshots
 * @param sample_count       Number of 32-bit snapshots to send
 * @return true if all frames were sent successfully
 */
bool usb_comm_send_pin_batches(uint64_t start_time_ps,
                               uint64_t sample_interval_ps,
                               uint32_t pin_mask,
                               const uint32_t *snapshots,
                               uint32_t sample_count);

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
 * Send a structured overflow report with dropped-batch and lost-sample counts.
 *
 * @param stream_name      Short stream label such as "Pin" or "ADC"
 * @param dropped_batches  Number of unread DMA batches that were overwritten
 * @param lost_samples     Number of samples contained in those dropped batches
 */
void usb_comm_send_overflow_report(const char *stream_name,
                                   uint32_t dropped_batches,
                                   uint32_t lost_samples);

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
 * Check if the CDC terminal is connected and ready.
 *
 * @return true if the host has opened the CDC interface
 */
bool usb_comm_connected(void);

#endif /* USB_COMM_H */
