#ifndef PICO_OSC_HAT_MODE_H
#define PICO_OSC_HAT_MODE_H

#include <stdint.h>
#include <stdbool.h>

/* Initialize hat mode (GPIO monitor + ADC) */
void hat_mode_init(void);

/* Start hat mode sampling */
void hat_mode_start(void);

/* Stop hat mode sampling */
void hat_mode_stop(void);

/* Main loop tick for hat mode: sample and send data over USB */
void hat_mode_tick(void);

/* Check if hat mode is currently active */
bool hat_mode_is_active(void);

#endif /* PICO_OSC_HAT_MODE_H */
