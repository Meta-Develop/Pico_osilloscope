/**
 * adc_sampler.h — 4-Channel ADC Sampler
 *
 * DMA-based continuous ADC sampling for oscilloscope mode.
 * Supports 1-4 channel round-robin with configurable sample rate.
 */

#ifndef ADC_SAMPLER_H
#define ADC_SAMPLER_H

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize ADC hardware and DMA for multi-channel sampling.
 *
 * @param channel_mask Bitmask of ADC channels to enable (0x0F = all 4)
 */
void adc_sampler_init(uint8_t channel_mask);

/**
 * Start continuous ADC sampling.
 * Samples are collected via DMA into ping-pong buffers.
 */
void adc_sampler_start(void);

/**
 * Stop ADC sampling.
 */
void adc_sampler_stop(void);

/**
 * Get the number of samples available in the read buffer.
 *
 * @return Number of 16-bit ADC samples ready
 */
uint32_t adc_sampler_available(void);

/**
 * Read ADC samples from the buffer.
 * Samples are interleaved by channel in round-robin order.
 *
 * @param buffer Output buffer for 16-bit samples
 * @param count  Maximum number of samples to read
 * @param start_time_ps Output timestamp of the first returned sample
 * @param sample_interval_ps Output interval between interleaved ADC samples
 * @return Actual number of samples read
 */
uint32_t adc_sampler_read(uint16_t *buffer,
						  uint32_t count,
						  uint64_t *start_time_ps,
						  uint64_t *sample_interval_ps);

/**
 * Set the ADC sample rate divider.
 * Effective rate = 48MHz / (96 * (1 + divider)).
 *
 * @param divider Clock divider value (0 = fastest)
 */
void adc_sampler_set_divider(uint16_t divider);

/**
 * Get the number of active ADC channels.
 *
 * @return Channel count (1-4)
 */
uint8_t adc_sampler_channel_count(void);

/**
 * Get the interval between interleaved ADC samples.
 *
 * @return Sample interval in picoseconds
 */
uint64_t adc_sampler_sample_interval_ps(void);

/**
 * Read and clear the number of unread DMA buffers that were overwritten.
 *
 * @return Number of detected ADC capture overruns since the last call
 */
uint32_t adc_sampler_take_overrun_count(void);

/**
 * Check if ADC sampler is running.
 *
 * @return true if sampling is active
 */
bool adc_sampler_is_running(void);

#endif /* ADC_SAMPLER_H */
