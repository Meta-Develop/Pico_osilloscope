#ifndef PICO_OSC_ADC_SAMPLER_H
#define PICO_OSC_ADC_SAMPLER_H

#include <stdint.h>
#include <stdbool.h>

/* Initialize ADC hardware and DMA */
void adc_sampler_init(void);

/* Start continuous ADC sampling with DMA */
void adc_sampler_start(uint32_t sample_rate_hz);

/* Stop ADC sampling */
void adc_sampler_stop(void);

/* Check if a DMA buffer is ready for reading */
bool adc_sampler_buffer_ready(void);

/* Get pointer to completed sample buffer and its length.
   Returns NULL if no buffer is ready. */
const uint16_t *adc_sampler_get_buffer(uint32_t *out_len);

/* Release the buffer after reading */
void adc_sampler_release_buffer(void);

/* Set which ADC channels to sample (bitmask, bits 0-2 for ADC0-ADC2) */
void adc_sampler_set_channels(uint8_t channel_mask);

#endif /* PICO_OSC_ADC_SAMPLER_H */
