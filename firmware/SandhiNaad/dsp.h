#pragma once

struct ComplexFloat {
    float real;
    float imag;
};

class Biquad {
public:
    float b0, b1, b2, a1, a2;
    float z1, z2;
    
    Biquad();
    void set_hpf(float fs, float f0, float q);
    void set_lpf(float fs, float f0, float q);
    float process(float in);
    void reset();
};

class FilterCascade {
public:
    Biquad hp1, hp2;
    Biquad lp1;
    
    FilterCascade();
    void init(float sample_rate);
    float process(float in);
    void reset();
};

class EnvelopeFollower {
public:
    float alpha;
    float env;
    
    EnvelopeFollower();
    void init(float fs, float fc);
    float process(float in);
    void reset();
};

void apply_hann_window(float* data, int length);
void fft_512(ComplexFloat* data);
