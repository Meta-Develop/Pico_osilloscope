/**
 * hat_mode.h — Hat Mode: All-Digital GPIO Monitoring
 *
 * Monitors all TargetPico GPIO pins as digital logic.
 * Uses PIO for high-speed parallel sampling.
 */

#ifndef HAT_MODE_H
#define HAT_MODE_H

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize hat mode.
 * Configures all GPIO pins as digital inputs and sets up PIO sampling.
 */
void hat_mode_init(void);

/**
 * Run hat mode main loop (blocking).
 * Continuously samples GPIO states and streams data over USB.
 * Returns when a CMD_STOP or CMD_MODE command is received.
 *
 * @return New mode to switch to (MODE_HAT or MODE_OSCILLOSCOPE),
 *         or -1 if stopped without mode change.
 */
int hat_mode_run(void);

/**
 * Stop hat mode and release resources.
 */
void hat_mode_stop(void);

#endif /* HAT_MODE_H */
