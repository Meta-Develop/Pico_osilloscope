#ifndef PICO_OSC_CONFIG_H
#define PICO_OSC_CONFIG_H

/* --- Version --- */
#define FIRMWARE_VERSION_MAJOR  0
#define FIRMWARE_VERSION_MINOR  1
#define FIRMWARE_VERSION_PATCH  0

/* --- Operating Modes --- */
#define MODE_HAT            0
#define MODE_OSCILLOSCOPE   1
#define DEFAULT_MODE        MODE_HAT

/* --- ADC Configuration --- */
#define ADC_NUM_CHANNELS    3       /* ADC0-ADC2 (GPIO26-28) */
#define ADC_SAMPLE_RATE_HZ  100000  /* 100 ksps default */
#define ADC_RESOLUTION_BITS 12
#define ADC_MAX_VALUE       4095
#define ADC_VREF            3.3f

/* --- GPIO Monitoring (Hat Mode) --- */
#define PIN_MONITOR_FIRST_GPIO  0
#define PIN_MONITOR_LAST_GPIO   22
#define PIN_MONITOR_COUNT       23  /* GPIO0-GPIO22 */
#define PIN_MONITOR_SAMPLE_HZ   10000  /* 10 kHz default */

/* --- Status LED --- */
#define LED_PIN             25

/* --- Communication Protocol --- */
#define PROTO_SYNC_BYTE     0xAA
#define PROTO_MAX_PAYLOAD   4096

/* Message types: Pico -> PC */
#define MSG_PIN_DATA        0x01
#define MSG_ADC_DATA        0x02
#define MSG_WAVE_DATA       0x03
#define MSG_STATUS          0x20
#define MSG_ERROR           0xFF

/* Message types: PC -> Pico */
#define CMD_CONFIG          0x10
#define CMD_START           0x11
#define CMD_STOP            0x12
#define CMD_MODE            0x13

/* --- DMA --- */
#define ADC_DMA_CHANNEL     0
#define ADC_DMA_BUF_SIZE    1024  /* samples per buffer */

/* --- USB CDC --- */
#define USB_TX_BUF_SIZE     4096
#define USB_RX_BUF_SIZE     256

#endif /* PICO_OSC_CONFIG_H */
