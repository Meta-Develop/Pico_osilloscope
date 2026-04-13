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
static uint8_t active_channels = 0;
static uint8_t channel_mask_config = 0;
static bool running = false;

/* Ping-pong buffers */
static uint16_t __attribute__((aligned(ADC_BUFFER_SIZE * 2)))
    adc_buf_a[ADC_BUFFER_SIZE];
static uint16_t __attribute__((aligned(ADC_BUFFER_SIZE * 2)))
    adc_buf_b[ADC_BUFFER_SIZE];
static volatile uint16_t *read_buf = adc_buf_a;
static volatile uint32_t samples_ready = 0;
static volatile bool buf_ready = false;

static void adc_dma_irq_handler(void) {
    if (dma_hw->ints1 & (1u << dma_chan)) {
        dma_hw->ints1 = (1u << dma_chan);

        /* Swap buffers */
        if (dma_channel_hw_addr(dma_chan)->write_addr == (uintptr_t)adc_buf_b) {
            read_buf = adc_buf_a;
            dma_channel_set_write_addr(dma_chan, adc_buf_b, true);
        } else {
            read_buf = adc_buf_b;
            dma_channel_set_write_addr(dma_chan, adc_buf_a, true);
        }
        samples_ready = ADC_BUFFER_SIZE;
        buf_ready = true;
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

    /* Configure round-robin if multiple channels */
    if (active_channels > 1) {
        adc_set_round_robin(channel_mask_config);
    } else {
        /* Single channel: find which one */
        for (uint8_t ch = 0; ch < ADC_CHANNELS; ch++) {
            if (channel_mask_config & (1u << ch)) {
                adc_select_input(ch);
                break;
            }
        }
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

    /* Fastest sampling: divider = 0 */
    adc_set_clkdiv(0);

    /* Configure DMA */
    dma_chan = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_16);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, DREQ_ADC);

    dma_channel_configure(
        dma_chan,
        &dc,
        adc_buf_a,        /* Write address */
        &adc_hw->fifo,    /* Read address */
        ADC_BUFFER_SIZE,   /* Transfer count */
        false              /* Don't start yet */
    );

    /* DMA interrupt on IRQ1 (IRQ0 used by pin_monitor) */
    dma_channel_set_irq1_enabled(dma_chan, true);
    irq_set_exclusive_handler(DMA_IRQ_1, adc_dma_irq_handler);
    irq_set_enabled(DMA_IRQ_1, true);
}

void adc_sampler_start(void) {
    if (running || active_channels == 0) return;

    buf_ready = false;
    samples_ready = 0;

    /* Start DMA */
    dma_channel_set_write_addr(dma_chan, adc_buf_a, true);

    /* Start ADC free-running */
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
    adc_set_clkdiv((float)divider);
}

uint8_t adc_sampler_channel_count(void) {
    return active_channels;
}

bool adc_sampler_is_running(void) {
    return running;
}
