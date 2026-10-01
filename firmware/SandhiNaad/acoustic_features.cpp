#include "acoustic_features.h"
#include <math.h>
#include <string.h>

// Large work buffers are static (NOT on the task stack): the audio task stack
// would otherwise overflow (512 complex + window + spectra ~ 8 KB).
static ComplexFloat fft_buf[512];
static float hann_win[512];
static bool  hann_ready = false;
static float mag2[256];

void compute_time_features(const float* x, int n, FeatBlockPayload* out) {
    if (n < 3) return;
    float peak = 0, mean = 0;
    for (int i = 0; i < n; i++) {
        mean += x[i];
        float a = fabsf(x[i]);
        if (a > peak) peak = a;
    }
    mean /= n;

    float m2 = 0, m3 = 0, m4 = 0, sum_sq = 0;
    float dx_ss = 0, ddx_ss = 0;
    int zc = 0;
    for (int i = 0; i < n; i++) {
        float d = x[i] - mean;
        float d2 = d * d;
        m2 += d2; m3 += d2 * d; m4 += d2 * d2;
        sum_sq += x[i] * x[i];
        if (i > 0) {
            if ((x[i] >= 0) != (x[i - 1] >= 0)) zc++;
            float dx = x[i] - x[i - 1];
            dx_ss += dx * dx;
            if (i > 1) {
                float ddx = x[i] - 2 * x[i - 1] + x[i - 2];
                ddx_ss += ddx * ddx;
            }
        }
    }
    m2 /= n; m3 /= n; m4 /= n;

    out->rms = sqrtf(sum_sq / n);
    out->peak_dbfs = 20.0f * log10f(peak + 1e-9f);
    out->zcr = (float)zc / (float)(n - 1);

    if (m2 > 1e-14f) {
        float sd = sqrtf(m2);
        out->skewness = m3 / (sd * sd * sd);
        out->kurtosis = m4 / (m2 * m2);
    } else {
        out->skewness = 0;
        out->kurtosis = 3.0f;
    }

    float var_dx = dx_ss / (n - 1);
    float var_ddx = ddx_ss / (n - 2);
    out->hjorth_activity = m2;
    if (m2 > 1e-14f && var_dx > 1e-14f) {
        out->hjorth_mobility = sqrtf(var_dx / m2);
        out->hjorth_complexity = sqrtf(var_ddx / var_dx) / out->hjorth_mobility;
    } else {
        out->hjorth_mobility = 0;
        out->hjorth_complexity = 0;
    }
}

void compute_spectral_features(const float* x, int n, int fs, FeatBlockPayload* out) {
    if (n > 512) n = 512;
    if (!hann_ready) {
        for (int i = 0; i < 512; i++) hann_win[i] = 1.0f;
        apply_hann_window(hann_win, 512);
        hann_ready = true;
    }
    for (int i = 0; i < 512; i++) {
        fft_buf[i].real = (i < n) ? x[i] * hann_win[i] : 0.0f;
        fft_buf[i].imag = 0.0f;
    }
    fft_512(fft_buf);

    const float bin_hz = (float)fs / 512.0f;
    float total = 0, fsum = 0, maxp = 0, peak_f = 0;
    float b1 = 0, b2 = 0, b3 = 0, b4 = 0;
    int nb = 0;
    for (int k = 0; k < 256; k++) {
        mag2[k] = fft_buf[k].real * fft_buf[k].real + fft_buf[k].imag * fft_buf[k].imag;
        float f = k * bin_hz;
        if (f < 250.0f || f > 4500.0f) continue;
        nb++;
        float p = mag2[k];
        total += p; fsum += f * p;
        if (p > maxp) { maxp = p; peak_f = f; }
        if (f < 500.0f) b1 += p;
        else if (f < 1000.0f) b2 += p;
        else if (f < 2000.0f) b3 += p;
        else b4 += p;
    }

    if (total > 1e-20f) {
        out->spectral_centroid = fsum / total;
        out->peak_freq = peak_f;
        out->subband_250_500 = b1 / total;
        out->subband_500_1k = b2 / total;
        out->subband_1k_2k = b3 / total;
        out->subband_2k_4k5 = b4 / total;
        out->hf_ratio = b4 / total;
        float h = 0;
        for (int k = 0; k < 256; k++) {
            float f = k * bin_hz;
            if (f < 250.0f || f > 4500.0f) continue;
            float p = mag2[k] / total;
            if (p > 0) h -= p * logf(p);
        }
        if (nb > 1) h /= logf((float)nb);
        out->spectral_entropy = h < 0 ? 0 : (h > 1 ? 1 : h);
    } else {
        out->spectral_centroid = out->peak_freq = 0;
        out->subband_250_500 = out->subband_500_1k = out->subband_1k_2k = out->subband_2k_4k5 = 0;
        out->hf_ratio = 0;
        out->spectral_entropy = 0;
    }
}
