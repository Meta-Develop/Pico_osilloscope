/**
 * adc_sampler.c — 4-Channel ADC Sampler
 *
 * DMA-based continuous ADC sampling with ping-pong buffer scheme.
 * Round-robin across enabled channels (up to 4).
 */

#include "adc_sampler.h"
#include "config.h"
#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/irq.h"
#include "pico/stdlib.h"
#include <string.h>

static int dma_chan = -1;
static bool initialized = false;
static uint8_t active_channels = 0;
static uint8_t channel_mask_config = 0;
static bool running = false;
static float clock_divider = 0.0f;

/* Ping-pong buffers */
static uint16_t __attribute__((aligned(ADC_BUFFER_SIZE * 2)))
    adc_buf_a[ADC_BUFFER_SIZE];
static uint16_t __attribute__((aligned(ADC_BUFFER_SIZE * 2)))
    adc_buf_b[ADC_BUFFER_SIZE];
static uint16_t *dma_target_buffer = adc_buf_a;
static volatile uint16_t *read_buf = adc_buf_a;
static volatile uint32_t samples_ready = 0;
static volatile bool buf_ready = false;

static uint8_t first_active_channel(void) {
    for (uint8_t ch = 0; ch < ADC_CHANNELS; ch++) {
        if (channel_mask_config & (1u << ch)) {
            return ch;
        }
    }

    return 0;
}

static void adc_dma_irq_handler(void) {
    if (dma_chan >= 0 && (dma_hw->ints1 & (1u << dma_chan))) {
        dma_hw->ints1 = (1u << dma_chan);

        read_buf = dma_target_buffer;
        samples_ready = ADC_BUFFER_SIZE;
        buf_ready = true;

        dma_target_buffer = (dma_target_buffer == adc_buf_a) ? adc_buf_b : adc_buf_a;
        dma_channel_transfer_to_buffer_now(dma_chan, dma_target_buffer, ADC_BUFFER_SIZE);
    }
}

void adc_sampler_init(uint8_t channel_mask) {
    channel_mask_config = channel_mask & 0x0F;

    adc_init();

    /* Count and configure active channels */
    active_channels = 0;
    for (uint8_t ch = 0; ch < ADC_CHANNELS; ch++) {
        if (channel_mask_config & (1u << ch)) {
            adc_gpio_init(GPIO_ADC_START + ch);
            active_channels++;
        }
    }

    if (active_channels == 0) {
        return;
    }

    adc_select_input(first_active_channel());

    /* Configure round-robin if multiple channels */
    if (active_channels > 1) {
        adc_set_round_robin(channel_mask_config);
    } else {
        adc_set_round_robin(0);
    }

    /* Free-running mode */
    adc_fifo_setup(
        true,   /* Enable FIFO */
        true,   /* Enable DMA request */
        1,      /* DREQ threshold */
        false,  /* No error bit */
        false   /* No byte shift (keep 12-bit) */
    );

    adc_set_clkdiv(clock_divider);

    if (!initialized) {
        dma_chan = dma_claim_unused_channel(true);
        dma_channel_config dc = dma_channel_get_default_config(dma_chan);
        channel_config_set_transfer_data_size(&dc, DMA_SIZE_16);
        channel_config_set_read_increment(&dc, false);
        channel_config_set_write_increment(&dc, true);
        channel_config_set_dreq(&dc, DREQ_ADC);

        dma_channel_configure(
            dma_chan,
            &dc,
            adc_buf_a,
            &adc_hw->fifo,
            ADC_BUFFER_SIZE,
            false
        );

        dma_channel_set_irq1_enabled(dma_chan, true);
        irq_set_exclusive_handler(DMA_IRQ_1, adc_dma_irq_handler);
        irq_set_enabled(DMA_IRQ_1, true);
        initialized = true;
    }
}

void adc_sampler_start(void) {
    if (!initialized || running || active_channels == 0) return;

    buf_ready = false;
    samples_ready = 0;
    read_buf = adc_buf_a;
    dma_target_buffer = adc_buf_a;

    adc_fifo_drain();
    dma_channel_abort(dma_chan);

    dma_channel_transfer_to_buffer_now(dma_chan, dma_target_buffer, ADC_BUFFER_SIZE);

    adc_run(true);
    running = true;
}

void adc_sampler_stop(void) {
    if (!running) return;

    adc_run(false);
    adc_fifo_drain();
    dma_channel_abort(dma_chan);
    running = false;
}

uint32_t adc_sampler_available(void) {
    return buf_ready ? samples_ready : 0;
}

uint32_t adc_sampler_read(uint16_t *buffer, uint32_t count) {
    if (!buf_ready || samples_ready == 0) {
        return 0;
    }

    uint32_t to_read = (count < samples_ready) ? count : samples_ready;
    memcpy(buffer, (const void *)read_buf, to_read * sizeof(uint16_t));

    buf_ready = false;
    samples_ready = 0;
    return to_read;
}

void adc_sampler_set_divider(uint16_t divider) {
    clock_divider = (float)divider;
    adc_set_clkdiv(clock_divider);
}

uint8_t adc_sampler_channel_count(void) {
    return active_channels;
}

bool adc_sampler_is_running(void) {
    return running;
}
