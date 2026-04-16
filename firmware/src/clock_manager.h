/**
 * clock_manager.h — System Clock Setup
 *
 * Applies the configured RP2350 system clock before USB initialization.
 */

#ifndef CLOCK_MANAGER_H
#define CLOCK_MANAGER_H

/**
 * Apply the configured system clock target if it exceeds the default clock.
 */
void clock_manager_init(void);

#endif /* CLOCK_MANAGER_H */
