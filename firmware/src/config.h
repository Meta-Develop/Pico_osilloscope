/**
 * config.h — Pico Oscilloscope Configuration
 *
 * Pin mapping, protocol constants, and hardware configuration
 * for both Hat Mode and Oscilloscope Mode.
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <stdint.h>

/* ---------- Operating Modes ---------- */
#define MODE_HAT          0   /* All GPIO as digital logic */
#define MODE_OSCILLOSCOPE 1   /* 4ch ADC + remaining digital */

/* ---------- GPIO Configuration ---------- */
#define GPIO_COUNT        30  /* GPIO0-GPIO29 */
#define GPIO_LED          25  /* Onboard LED */
#define GPIO_ADC_START    26  /* First ADC-capable GPIO */
#define GPIO_ADC_END      29  /* Last ADC-capable GPIO */

/* GPIO23 and GPIO24 are not exposed on Pico 2 */
#define GPIO_NOT_EXPOSED_0 23
#define GPIO_NOT_EXPOSED_1 24

/* Hat mode: all GPIOs as digital (GPIO0-22, 25-29), minus LED */
/* Oscilloscope mode digital: GPIO0-22 */
#define HAT_DIGITAL_MASK  0x3FE7FFFF  /* GPIO0-22, GPIO25-29 (bit mask) */
#define OSC_DIGITAL_MASK  0x007FFFFF  /* GPIO0-22 (bit mask) */

/* ---------- ADC Configuration ---------- */
#define ADC_CHANNELS      4   /* ADC0-ADC3 (GPIO26-29) */
#define ADC_RESOLUTION    12  /* 12-bit */
#define ADC_MAX_VALUE     4095
#define ADC_VREF          3.3f
#define ADC_MAX_SAMPLE_RATE 500000  /* 500 ksps shared */

/* Default sample rate per channel (4ch round-robin) */
#define ADC_DEFAULT_RATE  (ADC_MAX_SAMPLE_RATE / ADC_CHANNELS)

/* ---------- Sampling Buffers ---------- */
#define ADC_BUFFER_SIZE   4096   /* Samples per ADC buffer (DMA) */
#define PIN_BUFFER_SIZE   4096   /* GPIO snapshots per buffer */
#define USB_TX_BUFFER_SIZE 8192  /* USB transmit buffer bytes */

/* DMA ping-pong: 2 buffers per channel */
#define ADC_BUFFER_COUNT  2

/* ---------- PIO Configuration ---------- */
/* PIO0: primary digital sampling */
/* PIO1: secondary / oscilloscope digital */
#define PIO_SAMPLE_PIN_BASE  0   /* Start sampling from GPIO0 */
#define PIO_SAMPLE_PIN_COUNT 30  /* Sample GPIO0-29 */

/* ---------- Communication Protocol ---------- */
#define PROTO_SYNC        0xAA

/* Message types: Pico -> PC */
#define MSG_PIN_DATA      0x01  /* GPIO pin state snapshots */
#define MSG_ADC_DATA      0x02  /* ADC sample data */
#define MSG_TRIGGER       0x03  /* Trigger event */
#define MSG_STATUS        0x20  /* Status response */
#define MSG_ERROR         0xFF  /* Error */

/* Command types: PC -> Pico */
#define CMD_CONFIG        0x10  /* Configuration */
#define CMD_START         0x11  /* Start sampling */
#define CMD_STOP          0x12  /* Stop sampling */
#define CMD_MODE          0x13  /* Switch mode */
#define CMD_TRIGGER       0x14  /* Configure trigger */

/* Protocol limits */
#define PROTO_MAX_PAYLOAD 4096
#define PROTO_HEADER_SIZE 4     /* SYNC + TYPE + LENGTH(2) */
#define PROTO_CRC_SIZE    1

/* ---------- CRC-8 MAXIM ---------- */
#define CRC8_POLY         0x31
#define CRC8_INIT         0x00

/* ---------- Trigger Configuration ---------- */
#define TRIGGER_NONE      0
#define TRIGGER_RISING    1
#define TRIGGER_FALLING   2
#define TRIGGER_BOTH      3

/* ---------- Status Codes ---------- */
#define STATUS_OK         0x00
#define STATUS_BUSY       0x01
#define STATUS_ERROR      0x02
#define STATUS_OVERFLOW   0x03

/* ---------- Timing ---------- */
#define LED_BLINK_MS      500   /* Status LED blink interval */
#define USB_POLL_MS       1     /* USB polling interval */

#endif /* CONFIG_H */
