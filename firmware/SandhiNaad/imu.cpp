#include "imu.h"
#include "config.h"
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <esp_timer.h>
#include <math.h>
#include <string.h>
#include <stdio.h>

static Adafruit_BNO055 bno_thigh(55, BNO055_ADDRESS_THIGH, &Wire);
static Adafruit_BNO055 bno_shank(56, BNO055_ADDRESS_SHANK, &Wire);
static bool thigh_ok = false, shank_ok = false;

static portMUX_TYPE imu_mux = portMUX_INITIALIZER_UNLOCKED;
static ImuPayload payload = {};
static CycleData last_cycle = {};
static CycleData cur = {};
static float cur_min_angle = 1e9f, cur_max_angle = -1e9f;
static uint32_t cycle_counter = 0;
static volatile int pending_events = 0;
static volatile bool cal_zero_requested = false;

static float q_ref_w = 1, q_ref_x = 0, q_ref_y = 0, q_ref_z = 0;
static uint64_t last_time = 0, cycle_start = 0, last_probe = 0;
static float filtered_vel = 0, prev_angle = 0;
static bool have_prev = false;
static bool single_mode_logged = false;
static int  bad_reads[2] = {0, 0};        // consecutive invalid quaternions (thigh, shank)
static bool data_ok[2] = {false, false};  // latest quaternion valid?
static bool ref_set = false;              // CAL_ZERO reference captured?

static bool start_bno(Adafruit_BNO055& b, uint8_t addr);

// Valid unit quaternion? (all-zero or garbage reads fail this)
static bool quat_valid(const imu::Quaternion& q) {
    float n = q.w() * q.w() + q.x() * q.x() + q.y() * q.y() + q.z() * q.z();
    return n > 0.64f && n < 1.44f;
}

// Read one BNO055; on success write normalised quaternion into w,x,y,z.
// After 1 s of bad data the sensor is re-initialised.
static bool read_bno(Adafruit_BNO055& b, uint8_t addr, int idx, bool& ok_flag,
                     float& w, float& x, float& y, float& z) {
    imu::Quaternion q = b.getQuat();
    if (quat_valid(q)) {
        float n = sqrtf(q.w() * q.w() + q.x() * q.x() + q.y() * q.y() + q.z() * q.z());
        w = q.w() / n; x = q.x() / n; y = q.y() / n; z = q.z() / n;
        if (!data_ok[idx]) send_log("IMU 0x%02X: orientation data OK", addr);
        data_ok[idx] = true;
        bad_reads[idx] = 0;
        return true;
    }
    data_ok[idx] = false;
    if (++bad_reads[idx] == 100) {
        send_log("IMU 0x%02X: returning zeros/invalid data for 1 s -> re-initialising", addr);
        ok_flag = start_bno(b, addr);
        bad_reads[idx] = 0;
    }
    return false;
}

static bool probe(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
}

static bool start_bno(Adafruit_BNO055& b, uint8_t addr) {
    if (!probe(addr)) return false;
    for (int i = 0; i < 3; i++) {
        // NOTE: no setExtCrystalUse(true) — most low-cost BNO055 boards (GY/CJMCU purple)
        // have NO 32 kHz crystal, and enabling it stalls fusion => all-zero quaternions.
        if (b.begin(OPERATION_MODE_NDOF)) { delay(30); return true; }
        delay(20);
    }
    return false;
}

void imu_init() {
    Wire.begin(I2C_SDA, I2C_SCL);
    Wire.setClock(100000);        // BNO055 clock-stretching is unreliable above 100k on ESP32
    Wire.setTimeOut(50);
    // Boot diagnostic: list every device on the I2C bus (shows up in the UI Log tab)
    char found[160] = "";
    int nfound = 0;
    for (uint8_t addr = 0x08; addr < 0x78; addr++) {
        if (probe(addr)) {
            char tmp[8];
            snprintf(tmp, sizeof(tmp), " 0x%02X", addr);
            strncat(found, tmp, sizeof(found) - strlen(found) - 1);
            nfound++;
        }
    }
    send_log("I2C scan (SDA=%d SCL=%d): %d device(s):%s  [expect 0x28 thigh + 0x29 shank]",
             I2C_SDA, I2C_SCL, nfound, nfound ? found : " none");
    thigh_ok = start_bno(bno_thigh, BNO055_ADDRESS_THIGH);
    shank_ok = start_bno(bno_shank, BNO055_ADDRESS_SHANK);
    payload.status_thigh = thigh_ok ? ST_ATTACHED : ST_NOT_ATTACHED;
    payload.status_shank = shank_ok ? ST_ATTACHED : ST_NOT_ATTACHED;
    payload.qw_thigh = payload.qw_shank = 1.0f;
    last_time = cycle_start = last_probe = esp_timer_get_time();
}

static inline void qmul(float w1, float x1, float y1, float z1,
                        float w2, float x2, float y2, float z2,
                        float& w, float& x, float& y, float& z) {
    w = w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2;
    x = w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2;
    y = w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2;
    z = w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2;
}

// Hot-plug check every 500 ms (Test 1: badges must follow unplug/replug).
static void check_presence(uint64_t now) {
    if (now - last_probe < 500000ULL) return;
    last_probe = now;
    bool t = probe(BNO055_ADDRESS_THIGH);
    bool s = probe(BNO055_ADDRESS_SHANK);
    if (t && !thigh_ok) thigh_ok = start_bno(bno_thigh, BNO055_ADDRESS_THIGH);
    if (!t) thigh_ok = false;
    if (s && !shank_ok) shank_ok = start_bno(bno_shank, BNO055_ADDRESS_SHANK);
    if (!s) shank_ok = false;
}

void imu_update() {
    uint64_t now = esp_timer_get_time();
    float dt = (now - last_time) / 1e6f;
    if (dt <= 0) dt = 0.01f;
    last_time = now;
    check_presence(now);

    ImuPayload p;
    portENTER_CRITICAL(&imu_mux);
    p = payload;
    portEXIT_CRITICAL(&imu_mux);

    bool fresh = false;
    if (thigh_ok) {
        float w = p.qw_thigh, x = p.qx_thigh, y = p.qy_thigh, z = p.qz_thigh;
        if (read_bno(bno_thigh, BNO055_ADDRESS_THIGH, 0, thigh_ok, w, x, y, z)) {
            p.qw_thigh = w; p.qx_thigh = x; p.qy_thigh = y; p.qz_thigh = z;
            fresh = true;
        }
        uint8_t s, g, a, m;
        bno_thigh.getCalibration(&s, &g, &a, &m);
        p.cal_sys = s; p.cal_gyro = g; p.cal_accel = a; p.cal_mag = m;
    }
    if (shank_ok) {
        float w = p.qw_shank, x = p.qx_shank, y = p.qy_shank, z = p.qz_shank;
        if (read_bno(bno_shank, BNO055_ADDRESS_SHANK, 1, shank_ok, w, x, y, z)) {
            p.qw_shank = w; p.qx_shank = x; p.qy_shank = y; p.qz_shank = z;
            fresh = true;
        }
    }
    p.status_thigh = thigh_ok ? ST_ATTACHED : ST_NOT_ATTACHED;
    p.status_shank = shank_ok ? ST_ATTACHED : ST_NOT_ATTACHED;
    // Single-IMU mode: a missing sensor is treated as a fixed reference
    // (identity). Valid for the SEATED protocol: thigh rests on the chair,
    // strap the one working IMU on the shank and press CAL_ZERO with the leg
    // hanging. Angle = rotation of that IMU from its zero pose.
    if (!thigh_ok) { p.qw_thigh = 1; p.qx_thigh = p.qy_thigh = p.qz_thigh = 0; }
    if (!shank_ok) { p.qw_shank = 1; p.qx_shank = p.qy_shank = p.qz_shank = 0; }
    if (thigh_ok != shank_ok && !single_mode_logged) {
        send_log("IMU: only %s found -> single-IMU mode (strap it on the SHANK, sit, press Calibrate zero)",
                 thigh_ok ? "0x28" : "0x29");
        single_mode_logged = true;
    }
    if (thigh_ok && shank_ok) single_mode_logged = false;

    // relative rotation thigh -> shank
    float rw, rx, ry, rz;
    qmul(p.qw_thigh, -p.qx_thigh, -p.qy_thigh, -p.qz_thigh,
         p.qw_shank, p.qx_shank, p.qy_shank, p.qz_shank, rw, rx, ry, rz);
    // Reference pose: set by CAL_ZERO, or automatically on the first valid sample
    // so the angle starts at 0 deg instead of an arbitrary value.
    if ((cal_zero_requested || !ref_set) && fresh) {
        q_ref_w = rw; q_ref_x = rx; q_ref_y = ry; q_ref_z = rz;
        if (cal_zero_requested) send_log("CAL_ZERO done: current pose = 0 deg");
        else send_log("IMU: reference pose auto-captured (press Calibrate zero with leg in start position)");
        cal_zero_requested = false;
        ref_set = true;
        have_prev = false;
        filtered_vel = 0;
        cur = {};
        cur_min_angle = 1e9f; cur_max_angle = -1e9f;
        cycle_start = now;
    } else if (cal_zero_requested && !(thigh_ok || shank_ok)) {
        send_log("CAL_ZERO failed: no IMU delivering data");
        cal_zero_requested = false;
    }
    float aw, ax, ay, az;
    qmul(q_ref_w, -q_ref_x, -q_ref_y, -q_ref_z, rw, rx, ry, rz, aw, ax, ay, az);
    float c = fabsf(aw);
    if (c > 1.0f) c = 1.0f;
    float angle = (thigh_ok || shank_ok) ? 2.0f * acosf(c) * 57.2957795f : 0.0f;

    float vel = have_prev ? (angle - prev_angle) / dt : 0.0f;
    prev_angle = angle; have_prev = true;
    filtered_vel = 0.8f * filtered_vel + 0.2f * vel;
    p.knee_angle = angle;
    p.angular_vel = filtered_vel;

    // Phase with hysteresis: enter at |v|>5 deg/s, stay while |v|>3 deg/s
    uint8_t old = p.phase;
    if (filtered_vel > 5.0f || (old == 1 && filtered_vel > 3.0f)) p.phase = 1;
    else if (filtered_vel < -5.0f || (old == 2 && filtered_vel < -3.0f)) p.phase = 2;
    else p.phase = 0;

    // A cycle = flexion onset -> next flexion onset
    int ev = pending_events; pending_events = 0;
    cur.num_events += ev;
    CycleData finished = {};
    bool completed = false;
    if (old != 1 && p.phase == 1) {
        float dur = (now - cycle_start) / 1e6f;
        if (dur > 0.5f && cur_max_angle > cur_min_angle) {
            cur.rom = cur_max_angle - cur_min_angle;
            cur.duration_s = dur;
            cur.id = ++cycle_counter;
            finished = cur;
            completed = true;
        }
        cur = {};
        cur_min_angle = 1e9f; cur_max_angle = -1e9f;
        cycle_start = now;
    }
    if (p.phase == 1 && filtered_vel > cur.peak_flex_vel) cur.peak_flex_vel = filtered_vel;
    if (p.phase == 2 && filtered_vel < cur.peak_ext_vel) cur.peak_ext_vel = filtered_vel;
    if (angle < cur_min_angle) cur_min_angle = angle;
    if (angle > cur_max_angle) cur_max_angle = angle;

    portENTER_CRITICAL(&imu_mux);
    payload = p;
    if (completed) last_cycle = finished;
    portEXIT_CRITICAL(&imu_mux);

    send_packet(PKT_IMU, now, &p, sizeof(p));   // IMU is sent in every stream mode
}

ImuPayload imu_get_payload() {
    portENTER_CRITICAL(&imu_mux);
    ImuPayload p = payload;
    portEXIT_CRITICAL(&imu_mux);
    return p;
}
float imu_get_knee_angle() { return imu_get_payload().knee_angle; }
uint8_t imu_get_phase() { return imu_get_payload().phase; }
CycleData imu_get_last_cycle() {
    portENTER_CRITICAL(&imu_mux);
    CycleData c = last_cycle;
    portEXIT_CRITICAL(&imu_mux);
    return c;
}
void imu_add_event_to_cycle() { pending_events = pending_events + 1; }
void imu_request_cal_zero() { cal_zero_requested = true; }
