add_executable(pico_oscilloscope
    main.c
    adc_sampler.c
    pin_monitor.c
    usb_comm.c
    hat_mode.c
)

target_include_directories(pico_oscilloscope PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(pico_oscilloscope
    pico_stdlib
    hardware_adc
    hardware_dma
    hardware_gpio
    hardware_pio
    pico_multicore
)

# USB CDC for serial communication
pico_enable_stdio_usb(pico_oscilloscope 1)
pico_enable_stdio_uart(pico_oscilloscope 0)

# Generate .uf2 output
pico_add_extra_outputs(pico_oscilloscope)

# RP2350 (Pico 2) target
set(PICO_BOARD pico2)
