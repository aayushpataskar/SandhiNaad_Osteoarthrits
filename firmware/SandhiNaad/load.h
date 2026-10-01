#pragma once
#include <stdint.h>

// HX711 + bar load cell (e.g. 10 kg). Bit-banged driver, no external library.
// Auto-detected: if DOUT never goes LOW the status is NOT_ATTACHED.
// Calibration (offset + counts/N) is stored in flash (NVS) and survives reboots.
void load_init();
void load_update();                 // call every ~10 ms from the sensor task
void load_request_tare();           // averages the next 16 readings as zero
void load_request_scale(float grams);   // known mass currently on the cell
uint8_t load_get_status();
float load_get_force_n();
