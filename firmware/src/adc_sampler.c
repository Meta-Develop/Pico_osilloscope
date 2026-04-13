#include "adc_sampler.h"
#include "config.h"

#include "hardware/adc.h"
#include "hardware/dma.h"
#include "hardware/irq.h"

static uint16_t dma_buf_a[ADC_DMA_BUF_SIZE] __attribute__((aligned(4)));
static uint16_t dma_buf_b[ADC_DMA_BUF_SIZE] __attribute__((aligned(4)));
static volatile bool buf_a_ready = false;
static volatile bool buf_b_ready = false;
static volatile bool using_buf_a = true;
static int dma_chan = -1;
static uint8_t active_channels = 0x07; /* ADC0-2 by default */

static void dma_irq_handler(void) {
    if (dma_channel_get_irq0_status(dma_chan)) {
        dma_channel_acknowledge_irq0(dma_chan);

        if (using_buf_a) {
            buf_a_ready = true;
            dma_channel_set_write_addr(dma_chan, dma_buf_b, true);
        } else {
            buf_b_ready = true;
            dma_channel_set_write_addr(dma_chan, dma_buf_a, true);
        }
        using_buf_a = !using_buf_a;
    }
}

void adc_sampler_init(void) {
    adc_init();

    /* Configure ADC pins */
    adc_gpio_init(26); /* ADC0 */
    adc_gpio_init(27); /* ADC1 */
    adc_gpio_init(28); /* ADC2 */

    /* Claim a DMA channel */
    dma_chan = dma_claim_unused_channel(true);
}

void adc_sampler_start(uint32_t sample_rate_hz) {
    /* Configure ADC for round-robin sampling */
    adc_select_input(0);
    adc_set_round_robin(active_channels);
    adc_fifo_setup(true, true, 1, false, false);

    /* Clock divider: 48MHz USB clock / desired rate */
    float clk_div = 48000000.0f / (float)sample_rate_hz;
    adc_set_clkdiv(clk_div - 1.0f);

    /* Configure DMA */
    dma_channel_config cfg = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&cfg, DMA_SIZE_16);
    channel_config_set_read_increment(&cfg, false);
    channel_config_set_write_increment(&cfg, true);
    channel_config_set_dreq(&cfg, DREQ_ADC);

    dma_channel_configure(dma_chan, &cfg,
        dma_buf_a,          /* write address */
        &adc_hw->fifo,      /* read address */
        ADC_DMA_BUF_SIZE,   /* transfer count */
        false               /* don't start yet */
    );

    /* Enable DMA IRQ */
    dma_channel_set_irq0_enabled(dma_chan, true);
    irq_set_exclusive_handler(DMA_IRQ_0, dma_irq_handler);
    irq_set_enabled(DMA_IRQ_0, true);

    buf_a_ready = false;
    buf_b_ready = false;
    using_buf_a = true;

    /* Start DMA and ADC */
    dma_channel_start(dma_chan);
    adc_run(true);
}

void adc_sampler_stop(void) {
    adc_run(false);
    adc_fifo_drain();
    dma_channel_abort(dma_chan);
    buf_a_ready = false;
    buf_b_ready = false;
}

bool adc_sampler_buffer_ready(void) {
    return buf_a_ready || buf_b_ready;
}

const uint16_t *adc_sampler_get_buffer(uint32_t *out_len) {
    if (buf_a_ready) {
        *out_len = ADC_DMA_BUF_SIZE;
        return dma_buf_a;
    }
    if (buf_b_ready) {
        *out_len = ADC_DMA_BUF_SIZE;
        return dma_buf_b;
    }
    *out_len = 0;
    return NULL;
}

void adc_sampler_release_buffer(void) {
    if (buf_a_ready) {
        buf_a_ready = false;
    } else if (buf_b_ready) {
        buf_b_ready = false;
    }
}

void adc_sampler_set_channels(uint8_t channel_mask) {
    active_channels = channel_mask & 0x07;
}
