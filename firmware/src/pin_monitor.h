/**
 * pin_monitor.h — PIO-Based GPIO Pin Monitor
 *
 * High-speed parallel GPIO sampling using PIO state machines.
 * Used in both Hat Mode (all pins) and Oscilloscope Mode (digital channels).
 */

#ifndef PIN_MONITOR_H
#define PIN_MONITOR_H

#include <stdint.h>
#include <stdbool.h>

/**
 * Initialize PIO-based pin monitoring.
 * Configures PIO0 for GPIO sampling and DMA for buffer transfers.
 *
 * @param pin_mask Bitmask of GPIO pins to monitor
 */
void pin_monitor_init(uint32_t pin_mask);

/**
 * Start continuous pin monitoring.
 * PIO samples GPIO states into DMA buffer continuously.
 */
void pin_monitor_start(void);

/**
 * Stop pin monitoring.
 */
void pin_monitor_stop(void);

/**
 * Get the current GPIO snapshot (single read).
 *
 * @return 32-bit value with each bit representing a GPIO state
 */
uint32_t pin_monitor_read_once(void);

/**
 * Get the number of buffered snapshots available.
 *
 * @return Number of 32-bit snapshots ready to read
 */
uint32_t pin_monitor_available(void);

/**
 * Read buffered pin snapshots.
 *
 * @param buffer Output buffer for 32-bit GPIO snapshots
 * @param count  Maximum number of snapshots to read
 * @param start_time_ps Output timestamp of the first returned snapshot
 * @param sample_interval_ps Output interval between snapshots
 * @return Actual number of snapshots read
 */
uint32_t pin_monitor_read(uint32_t *buffer,
						  uint32_t count,
						  uint64_t *start_time_ps,
						  uint64_t *sample_interval_ps);

/**
 * Check if pin monitor is currently running.
 *
 * @return true if sampling is active
 */
bool pin_monitor_is_running(void);

/**
 * Get the GPIO snapshot interval.
 *
 * @return Snapshot interval in picoseconds
 */
uint64_t pin_monitor_sample_interval_ps(void);

/**
 * Read and clear the number of unread DMA buffers that were overwritten.
 *
 * @return Number of detected pin capture overruns since the last call
 */
uint32_t pin_monitor_take_overrun_count(void);

/**
 * Set the sampling clock divider.
 * Effective sample rate = clk_sys / (PIO_SAMPLE_LOOP_CYCLES * divider).
 *
 * @param divider PIO clock divider (1.0 = system clock speed)
 */
void pin_monitor_set_divider(float divider);

#endif /* PIN_MONITOR_H */
