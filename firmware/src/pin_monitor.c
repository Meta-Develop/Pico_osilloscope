/**
 * pin_monitor.c — PIO-Based GPIO Pin Monitor
 *
 * Uses PIO to sample all GPIO pins in parallel at high speed.
 * DMA transfers snapshots to memory buffer for processing.
 */

#include "pin_monitor.h"
#include "config.h"
#include "hardware/pio.h"
#include "hardware/pio_instructions.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"
#include "pico/stdlib.h"

/* PIO program: read all GPIO pins and push to FIFO, looped via wrap. */
static uint16_t pin_sample_program[] = { 0, 0 };

static struct pio_program pin_sample_program_struct = {
    .instructions = pin_sample_program,
    .length = 2,
    .origin = -1,
};

static PIO pio = pio0;
static uint sm = 0;
static uint program_offset = 0;
static int dma_chan = -1;
static bool initialized = false;
static uint32_t pin_mask_config;
static bool running = false;
static float clock_divider = 1.0f;

/* Ping-pong DMA buffers */
static uint32_t __attribute__((aligned(PIN_BUFFER_SIZE * 4)))
    buffer_a[PIN_BUFFER_SIZE];
static uint32_t __attribute__((aligned(PIN_BUFFER_SIZE * 4)))
    buffer_b[PIN_BUFFER_SIZE];
static uint32_t *dma_target_buffer = buffer_a;
static volatile uint32_t *read_buffer = buffer_a;
static volatile uint32_t read_count = 0;
static volatile bool buffer_ready = false;

static void pin_monitor_configure_inputs(uint32_t pin_mask) {
    for (uint i = 0; i < GPIO_COUNT; i++) {
        if (pin_mask & (1u << i)) {
            pio_gpio_init(pio, i);
            gpio_set_dir(i, GPIO_IN);
            gpio_disable_pulls(i);
        }
    }
}

static void pin_monitor_configure_sm(void) {
    pio_sm_set_enabled(pio, sm, false);
    pio_sm_clear_fifos(pio, sm);
    pio_sm_restart(pio, sm);

    pio_sm_config c = pio_get_default_sm_config();
    sm_config_set_wrap(&c, program_offset, program_offset + 1);
    sm_config_set_in_pins(&c, PIO_SAMPLE_PIN_BASE);
    sm_config_set_in_shift(&c, false, true, 32);
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
    sm_config_set_clkdiv(&c, clock_divider);

    pio_sm_init(pio, sm, program_offset, &c);
}

/* DMA completion interrupt handler */
static void dma_irq_handler(void) {
    if (dma_chan >= 0 && (dma_hw->ints0 & (1u << dma_chan))) {
        dma_hw->ints0 = (1u << dma_chan);

        read_buffer = dma_target_buffer;
        read_count = PIN_BUFFER_SIZE;
        buffer_ready = true;

        dma_target_buffer = (dma_target_buffer == buffer_a) ? buffer_b : buffer_a;
        dma_channel_transfer_to_buffer_now(dma_chan, dma_target_buffer, PIN_BUFFER_SIZE);
    }
}

void pin_monitor_init(uint32_t pin_mask) {
    pin_mask_config = pin_mask;

    pin_monitor_configure_inputs(pin_mask_config);

    if (!initialized) {
        pin_sample_program[0] = pio_encode_in(pio_pins, 32);
        pin_sample_program[1] = pio_encode_push(false, true);
        program_offset = pio_add_program(pio, &pin_sample_program_struct);

        dma_chan = dma_claim_unused_channel(true);
        dma_channel_config dc = dma_channel_get_default_config(dma_chan);
        channel_config_set_transfer_data_size(&dc, DMA_SIZE_32);
        channel_config_set_read_increment(&dc, false);
        channel_config_set_write_increment(&dc, true);
        channel_config_set_dreq(&dc, pio_get_dreq(pio, sm, false));

        dma_channel_configure(
            dma_chan,
            &dc,
            buffer_a,
            &pio->rxf[sm],
            PIN_BUFFER_SIZE,
            false
        );

        dma_channel_set_irq0_enabled(dma_chan, true);
        irq_set_exclusive_handler(DMA_IRQ_0, dma_irq_handler);
        irq_set_enabled(DMA_IRQ_0, true);
        initialized = true;
    }

    pin_monitor_configure_sm();
}

void pin_monitor_start(void) {
    if (!initialized || running) return;

    buffer_ready = false;
    read_count = 0;
    read_buffer = buffer_a;
    dma_target_buffer = buffer_a;

    pio_sm_clear_fifos(pio, sm);
    pio_sm_restart(pio, sm);
    dma_channel_abort(dma_chan);

    /* Start DMA before enabling the state machine. */
    dma_channel_transfer_to_buffer_now(dma_chan, dma_target_buffer, PIN_BUFFER_SIZE);

    pio_sm_set_enabled(pio, sm, true);
    running = true;
}

void pin_monitor_stop(void) {
    if (!running) return;

    pio_sm_set_enabled(pio, sm, false);
    dma_channel_abort(dma_chan);
    pio_sm_clear_fifos(pio, sm);
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
    if (divider < 1.0f) {
        divider = 1.0f;
    }

    clock_divider = divider;

    if (initialized) {
        pio_sm_set_clkdiv(pio, sm, clock_divider);
    }
}
