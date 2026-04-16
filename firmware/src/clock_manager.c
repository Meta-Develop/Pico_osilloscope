/**
 * clock_manager.c — System Clock Setup
 *
 * Raises VREG before attempting a higher RP2350 system clock.
 */

#include "clock_manager.h"
#include "config.h"
#include "hardware/clocks.h"
#include "hardware/vreg.h"
#include "pico/stdlib.h"

#ifndef PICO_OSC_TARGET_SYS_CLOCK_KHZ
#define PICO_OSC_TARGET_SYS_CLOCK_KHZ 300000u
#endif

#define DEFAULT_SYSTEM_CLOCK_KHZ (SYSTEM_CLOCK_HZ / 1000u)
#define OVERCLOCK_VREG VREG_VOLTAGE_1_30
#define VREG_SETTLE_US 1000u

void clock_manager_init(void) {
    if (PICO_OSC_TARGET_SYS_CLOCK_KHZ <= DEFAULT_SYSTEM_CLOCK_KHZ) {
        return;
    }

    vreg_set_voltage(OVERCLOCK_VREG);
    sleep_us(VREG_SETTLE_US);

    (void)set_sys_clock_khz(PICO_OSC_TARGET_SYS_CLOCK_KHZ, false);
}
