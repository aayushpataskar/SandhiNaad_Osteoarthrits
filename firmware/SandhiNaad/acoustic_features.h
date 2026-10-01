#pragma once
#include "protocol.h"
#include "dsp.h"

// Definitions match ml/config.py + docs/DSP.md:
//   kurtosis = E[(x-mu)^4]/sigma^4   (Pearson, NOT excess)
//   zcr      = sign changes / N      (rate, 0..1)
void compute_time_features(const float* buffer, int length, FeatBlockPayload* out);
void compute_spectral_features(const float* buffer, int length, int sample_rate, FeatBlockPayload* out);
