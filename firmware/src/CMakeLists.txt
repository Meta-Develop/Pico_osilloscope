cmake_minimum_required(VERSION 3.13)

add_executable(pico_oscilloscope
    main.c
    usb_comm.c
    pin_monitor.c
    adc_sampler.c
    hat_mode.c
    osc_mode.c
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
    tinyusb_device
    tinyusb_board
)

# Enable USB serial output (CDC)
pico_enable_stdio_usb(pico_oscilloscope 1)
pico_enable_stdio_uart(pico_oscilloscope 0)

# Generate UF2 output for flashing
pico_add_extra_outputs(pico_oscilloscope)
