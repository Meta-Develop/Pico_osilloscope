/**
 * pin_monitor.c — PIO-Based GPIO Pin Monitor
 *
 * Uses PIO to sample all GPIO pins in parallel at high speed.
 * DMA transfers snapshots to memory buffer for processing.
 */

#include "pin_monitor.h"
#include "config.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"
#include "pico/stdlib.h"

/* PIO program: read all GPIO pins, push to FIFO
 *
 * .program pin_sample
 * loop:
 *     in pins, 32    ; Read all 32 GPIO bits
 *     push           ; Push to RX FIFO
 *     jmp loop
 */
static const uint16_t pin_sample_program[] = {
    0x4020,  /* in pins, 32 */
    0x8020,  /* push block */
    0x0000,  /* jmp 0 */
};

static const struct pio_program pin_sample_program_struct = {
    .instructions = pin_sample_program,
    .length = 3,
    .origin = -1,
};

static PIO pio = pio0;
static uint sm = 0;
static int dma_chan = -1;
static uint32_t pin_mask_config;
static bool running = false;

/* Ping-pong DMA buffers */
static uint32_t __attribute__((aligned(PIN_BUFFER_SIZE * 4)))
    buffer_a[PIN_BUFFER_SIZE];
static uint32_t __attribute__((aligned(PIN_BUFFER_SIZE * 4)))
    buffer_b[PIN_BUFFER_SIZE];
static volatile uint32_t *read_buffer = buffer_a;
static volatile uint32_t read_count = 0;
static volatile bool buffer_ready = false;

/* DMA completion interrupt handler */
static void dma_irq_handler(void) {
    if (dma_hw->ints0 & (1u << dma_chan)) {
        dma_hw->ints0 = (1u << dma_chan);

        /* Swap buffers */
        if (dma_channel_hw_addr(dma_chan)->write_addr == (uintptr_t)buffer_b) {
            read_buffer = buffer_a;
            dma_channel_set_write_addr(dma_chan, buffer_b, true);
        } else {
            read_buffer = buffer_b;
            dma_channel_set_write_addr(dma_chan, buffer_a, true);
        }
        read_count = PIN_BUFFER_SIZE;
        buffer_ready = true;
    }
}

void pin_monitor_init(uint32_t pin_mask) {
    pin_mask_config = pin_mask;

    /* Configure GPIO pins as inputs */
    for (uint i = 0; i < GPIO_COUNT; i++) {
        if (pin_mask & (1u << i)) {
            gpio_init(i);
            gpio_set_dir(i, GPIO_IN);
            gpio_pull_down(i);
        }
    }

    /* Load PIO program */
    uint offset = pio_add_program(pio, &pin_sample_program_struct);

    /* Configure state machine */
    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_wrap(&c, offset, offset + 2);
    sm_config_set_in_pins(&c, PIO_SAMPLE_PIN_BASE);
    sm_config_set_in_shift(&c, false, true, 32); /* Shift left, auto-push */
    sm_config_set_clkdiv(&c, 1.0f); /* Full speed */

    pio_sm_init(pio, sm, offset, &c);

    /* Configure DMA */
    dma_chan = dma_claim_unused_channel(true);
    dma_channel_config dc = dma_channel_get_default_config(dma_chan);
    channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
    channel_config_set_read_increment(&dc, false);
    channel_config_set_write_increment(&dc, true);
    channel_config_set_dreq(&dc, pio_get_dreq(pio, sm, false));

    dma_channel_configure(
        dma_chan,
        &dc,
        buffer_a,                     /* Write address */
        &pio->rxf[sm],               /* Read address (PIO RX FIFO) */
        PIN_BUFFER_SIZE,              /* Transfer count */
        false                         /* Don't start yet */
    );

    /* Set up DMA interrupt */
    dma_channel_set_irq0_enabled(dma_chan, true);
    irq_set_exclusive_handler(DMA_IRQ_0, dma_irq_handler);
    irq_set_enabled(DMA_IRQ_0, true);
}

void pin_monitor_start(void) {
    if (running) return;

    buffer_ready = false;
    read_count = 0;

    /* Start DMA */
    dma_channel_set_write_addr(dma_chan, buffer_a, true);

    /* Enable PIO state machine */
    pio_sm_set_enabled(pio, sm, true);
    running = true;
}

void pin_monitor_stop(void) {
    if (!running) return;

    pio_sm_set_enabled(pio, sm, false);
    dma_channel_abort(dma_chan);
    running = false;
}

uint32_t pin_monitor_read_once(void) {
    return gpio_get_all();
}

uint32_t pin_monitor_available(void) {
    return buffer_ready ? read_count : 0;
}

uint32_t pin_monitor_read(uint32_t *buffer, uint32_t count) {
    if (!buffer_ready || read_count == 0) {
        return 0;
    }

    uint32_t to_read = (count < read_count) ? count : read_count;
    for (uint32_t i = 0; i < to_read; i++) {
        buffer[i] = read_buffer[i] & pin_mask_config;
    }

    buffer_ready = false;
    read_count = 0;
    return to_read;
}

bool pin_monitor_is_running(void) {
    return running;
}

void pin_monitor_set_divider(float divider) {
    pio_sm_set_clkdiv(pio, sm, divider);
}
