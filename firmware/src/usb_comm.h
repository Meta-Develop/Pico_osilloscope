#ifndef PICO_OSC_USB_COMM_H
#define PICO_OSC_USB_COMM_H

#include <stdint.h>
#include <stdbool.h>

/* Initialize USB CDC communication */
void usb_comm_init(void);

/* Send a framed message: SYNC | TYPE | LEN(LE) | PAYLOAD | CRC8 */
bool usb_comm_send(uint8_t msg_type, const uint8_t *payload, uint16_t len);

/* Check if a complete command frame has been received */
bool usb_comm_cmd_available(void);

/* Read a received command. Returns message type, writes payload to buf.
   Returns 0 on no data. */
uint8_t usb_comm_read_cmd(uint8_t *buf, uint16_t *out_len, uint16_t buf_size);

/* Process incoming USB data (call from main loop) */
void usb_comm_poll(void);

/* CRC-8 (MAXIM/Dallas) calculation */
uint8_t crc8_maxim(const uint8_t *data, uint32_t len);

#endif /* PICO_OSC_USB_COMM_H */
