cmake_minimum_required(VERSION 3.13)

add_executable(pico_oscilloscope
    main.c
    clock_manager.c
    usb_comm.c
    pin_monitor.c
    adc_sampler.c
    hat_mode.c
    osc_mode.c
)

set(PICO_OSC_TARGET_SYS_CLOCK_KHZ 300000 CACHE STRING
    "Requested RP2350 system clock in kHz")

target_compile_definitions(pico_oscilloscope PRIVATE
    PICO_OSC_TARGET_SYS_CLOCK_KHZ=${PICO_OSC_TARGET_SYS_CLOCK_KHZ}
)

target_include_directories(pico_oscilloscope PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}
)

target_link_libraries(pico_oscilloscope
    pico_stdlib
    hardware_adc
    hardware_dma
    hardware_pio
    hardware_gpio
    hardware_clocks
    hardware_irq
    hardware_vreg
)

# Keep SDK-managed stdio USB enabled so the Pico reset/BOOTSEL path remains available.
pico_enable_stdio_usb(pico_oscilloscope 1)
pico_enable_stdio_uart(pico_oscilloscope 0)

# Generate UF2 output for flashing
pico_add_extra_outputs(pico_oscilloscope)
