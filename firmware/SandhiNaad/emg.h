#pragma once
#include <stdint.h>
#include "protocol.h"

void emg_init();            // starts its own 1 kHz sampling task
uint8_t emg_get_status();
float emg_get_envelope();
bool emg_is_saturated();
