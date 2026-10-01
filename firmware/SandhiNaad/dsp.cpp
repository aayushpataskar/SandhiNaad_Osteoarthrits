#include "dsp.h"
#include <cmath>
#include <stdint.h>

static constexpr float DSP_PI = 3.14159265358979323846f;

void apply_hann_window(float* data, int length) {
    for (int i = 0; i < length; i++) {
        float multiplier = 0.5f * (1.0f - cosf(2.0f * DSP_PI * i / (length - 1)));
        data[i] *= multiplier;
    }
}

static uint16_t reverse_bits(uint16_t x, int bits) {
    uint16_t y = 0;
    for (int i = 0; i < bits; i++) {
        y = (y << 1) | (x & 1);
        x >>= 1;
    }
    return y;
}

void fft_512(ComplexFloat* data) {
    const int N = 512;
    const int bits = 9; // log2(512)
    
    for (int i = 0; i < N; i++) {
        int j = reverse_bits(i, bits);
        if (i < j) {
            ComplexFloat temp = data[i];
            data[i] = data[j];
            data[j] = temp;
        }
    }
    
    for (int len = 2; len <= N; len <<= 1) {
        float angle = -2.0f * DSP_PI / len;
        ComplexFloat wlen = {cosf(angle), sinf(angle)};
        for (int i = 0; i < N; i += len) {
            ComplexFloat w = {1.0f, 0.0f};
            for (int j = 0; j < len / 2; j++) {
                ComplexFloat u = data[i + j];
                ComplexFloat v_in = data[i + j + len / 2];
                ComplexFloat v = {
                    v_in.real * w.real - v_in.imag * w.imag,
                    v_in.real * w.imag + v_in.imag * w.real
                };
                
                data[i + j].real = u.real + v.real;
                data[i + j].imag = u.imag + v.imag;
                data[i + j + len / 2].real = u.real - v.real;
                data[i + j + len / 2].imag = u.imag - v.imag;
                
                float next_w_real = w.real * wlen.real - w.imag * wlen.imag;
                float next_w_imag = w.real * wlen.imag + w.imag * wlen.real;
                w.real = next_w_real;
                w.imag = next_w_imag;
            }
        }
    }
}

Biquad::Biquad() : b0(1), b1(0), b2(0), a1(0), a2(0), z1(0), z2(0) {}

void Biquad::set_hpf(float fs, float f0, float q) {
    float w0 = 2.0f * DSP_PI * f0 / fs;
    float alpha = sinf(w0) / (2.0f * q);
    float cosw0 = cosf(w0);
    
    float a0 = 1.0f + alpha;
    b0 = (1.0f + cosw0) / 2.0f / a0;
    b1 = -(1.0f + cosw0) / a0;
    b2 = (1.0f + cosw0) / 2.0f / a0;
    a1 = -2.0f * cosw0 / a0;
    a2 = (1.0f - alpha) / a0;
}

void Biquad::set_lpf(float fs, float f0, float q) {
    float w0 = 2.0f * DSP_PI * f0 / fs;
    float alpha = sinf(w0) / (2.0f * q);
    float cosw0 = cosf(w0);
    
    float a0 = 1.0f + alpha;
    b0 = (1.0f - cosw0) / 2.0f / a0;
    b1 = (1.0f - cosw0) / a0;
    b2 = (1.0f - cosw0) / 2.0f / a0;
    a1 = -2.0f * cosw0 / a0;
    a2 = (1.0f - alpha) / a0;
}

float Biquad::process(float in) {
    float out = b0 * in + z1;
    z1 = b1 * in - a1 * out + z2;
    z2 = b2 * in - a2 * out;
    return out;
}

void Biquad::reset() {
    z1 = 0;
    z2 = 0;
}

FilterCascade::FilterCascade() {}

void FilterCascade::init(float sample_rate) {
    hp1.set_hpf(sample_rate, 250.0f, 0.5412f);
    hp2.set_hpf(sample_rate, 250.0f, 1.3066f);
    lp1.set_lpf(sample_rate, 4500.0f, 0.7071f);
}

float FilterCascade::process(float in) {
    return lp1.process(hp2.process(hp1.process(in)));
}

void FilterCascade::reset() {
    hp1.reset();
    hp2.reset();
    lp1.reset();
}

EnvelopeFollower::EnvelopeFollower() : alpha(0.0f), env(0.0f) {}

void EnvelopeFollower::init(float fs, float fc) {
    alpha = expf(-2.0f * DSP_PI * fc / fs);
    env = 0.0f;
}

float EnvelopeFollower::process(float in) {
    float rectified = fabsf(in);
    env = alpha * env + (1.0f - alpha) * rectified;
    return env;
}

void EnvelopeFollower::reset() {
    env = 0.0f;
}
