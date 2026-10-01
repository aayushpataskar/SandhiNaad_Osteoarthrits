#pragma once
#include <stdint.h>
#include "protocol.h"

struct CycleData {
    float rom;              // max - min knee angle within the cycle (deg)
    float peak_flex_vel;    // deg/s (positive)
    float peak_ext_vel;     // deg/s (negative)
    float duration_s;
    int   num_events;
    uint32_t id;            // increments every completed cycle (0 = none yet)
};

void imu_init();
void imu_update();          // call at 100 Hz from ONE task only (owns I2C)
ImuPayload imu_get_payload();
float   imu_get_knee_angle();
uint8_t imu_get_phase();
CycleData imu_get_last_cycle();
void imu_add_event_to_cycle();
void imu_request_cal_zero();
