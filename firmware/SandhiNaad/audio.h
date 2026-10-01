#pragma once
#include <stdint.h>

void audio_init();                 // installs I2S and starts the audio task (core 1)
float audio_get_noise_floor_dbfs();
int audio_get_live_slot();         // I2S slot used for analysis (0 or 1)
uint8_t audio_get_mic_status(int mic);   // mic 0 = I2S slot 0, mic 1 = slot 1
