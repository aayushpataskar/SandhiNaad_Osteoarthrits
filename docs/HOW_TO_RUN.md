# How to run SandhiNaad (firmware + UI)

There are two programs:

| Part | Where | Runs on |
|---|---|---|
| Firmware (`SandhiNaad.ino` + the `.cpp/.h` files next to it) | `firmware/SandhiNaad/` | ESP32 DevKit V1 |
| Desktop UI | `host/app.py` | your Windows laptop |

They "sync" over the USB cable. The ESP32 sends binary packets at **921600 baud**, and the UI decodes and plots them. They stay in sync automatically when the three items below match. Nothing else needs to be configured:

1. **Same baud:** 921600 (set in `config.h` → `BAUD_RATE`, and in the UI's baud box)
2. **Same protocol:** `firmware/SandhiNaad/protocol.h` ↔ `host/protocol.py` (already matched; change both together)
3. **Same model:** `ml/models/*.joblib` (used by the UI) ↔ `firmware/SandhiNaad/model.h` (used on the ESP32). Regenerate `model.h` whenever you retrain (step 4).

> Delete the old `firmware/src/` folder. It is Antigravity's first version, it is no longer built, and it has the bugs listed in the review.

---

## 0. Try the UI with no hardware (2 minutes)

```powershell
cd C:\Users\manoj\Desktop\sandhinaad\host
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
In the Port box, pick **SIMULATOR** and click **Connect**. All tabs should come alive with synthetic data. Use this to rehearse the demo.

---

## 1. Wiring (ESP32 DevKit V1)

| Sensor | Pin | ESP32 | Notes |
|---|---|---|---|
| INMP441 #1 | SCK / WS / SD | GPIO26 / GPIO25 / GPIO33 | L/R → **GND** |
| INMP441 #2 | SCK / WS / SD | GPIO26 / GPIO25 / GPIO33 (same bus) | L/R → **3V3** |
| both INMP441 | VDD / GND | 3V3 / GND | |
| BNO055 thigh | SDA / SCL / ADR | GPIO21 / GPIO22 / **GND** | address 0x28 |
| BNO055 shank | SDA / SCL / ADR | GPIO21 / GPIO22 / **3V3** | address 0x29 |
| AD8232 | OUTPUT / SDN / 3.3V / GND | GPIO34 / 3V3 / 3V3 / GND | quadriceps electrodes |
| AD8232 (optional) | LO+ / LO− | GPIO32 / GPIO35 | set `USE_EMG_LEADOFF 1` in config.h |
| HX711 | DT / SCK / VCC / GND | GPIO16 / GPIO17 / 3V3 / GND | 10 kg bar cell on E+/E−/A+/A− |

Any sensor can be missing. Its badge will show NOT_ATTACHED and everything else keeps working.

---

## 2. Upload the firmware — Arduino IDE (.ino)

1. Install **Arduino IDE 2.x**.
2. Go to **File → Preferences → Additional boards manager URLs** and add:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. Open **Boards Manager**, search **esp32 by Espressif**, and install version **2.0.17**. This build was checked against the 2.0.x API. 3.x may work but hasn't been tested with the legacy I2S driver used here.
4. Open **Library Manager** and install **Adafruit BNO055**. Click "Install all" so Adafruit Unified Sensor and BusIO come with it.
5. **File → Open →** `firmware\SandhiNaad\SandhiNaad.ino`. The other `.cpp/.h` files open as tabs automatically. The folder must stay named `SandhiNaad`.
6. Under **Tools**, set:
   - Board: **ESP32 Dev Module**
   - Upload Speed: 921600 (drop to 115200 if uploads fail)
   - Core Debug Level: **None**. This matters: debug text would corrupt the binary stream.
   - Port: your COM port (CP210x / CH340)
7. Click **Upload**. If it stays at `Connecting....`, hold the **BOOT** button on the board until the upload starts.
8. **Don't open the Serial Monitor.** The output is binary, so it looks like garbage, and while it's open the port is busy and the UI can't connect.

### Alternative: PlatformIO (VS Code)
```powershell
cd C:\Users\manoj\Desktop\sandhinaad\firmware
pio run -t upload
```
`platformio.ini` points at the same `SandhiNaad/` folder, so both tools build identical code.

---

## 3. Run the UI with the real board

1. Close the Arduino Serial Monitor.
2. Start the UI:
   ```powershell
   cd C:\Users\manoj\Desktop\sandhinaad\host
   .venv\Scripts\activate
   python app.py
   ```
3. Pick the ESP32's COM port, set baud to 921600, and click **Connect**. Opening the port resets the ESP32. The UI waits about 2.5 s for it to boot, then automatically sends `MODE`, `THRESH`, `START`.
4. Open the **Log** tab. You should see:
   `DEV SandhiNaad FW 1.1.0 booting`, then `DEV Boot: IMU thigh=OK shank=OK ...`, then `DEV SELFTEST model: ... PASS`.
5. With the IMUs held straight, click **Calibrate zero (IMU)**. For the load cell: with nothing on it, click **Tare**. Then place a known mass, enter its grams, and click **Scale**. The calibration is saved in the ESP32's flash and survives reboots.
6. Do slow seated flex–extend cycles. Each full cycle produces a risk update in the **Screening (ML)** tab. The on-device and host probabilities should show "match ✓".
7. To record: type a subject ID and click **Record**. Click again to stop. Files are saved to `host\sessions\<id>_<date>\`: `imu.csv, emg.csv, load.csv, events.csv, features.csv, cycles.csv, audio_filt.wav, meta.json`. All files share one device clock.

Stream modes (Mode box):
- **DEFAULT** (~55 kB/s) is the normal choice.
- **FULL** adds raw audio (~90 kB/s). It's close to the link limit at 921600. Use 2000000 baud only if your USB chip is a CH340 or CP2102N; for that, set `BAUD_RATE` in `config.h` and the UI to the same value.
- **FEATURES** (~15 kB/s) sends no waveforms.

---

## 4. Retrain the model and push it to the ESP32

```powershell
cd C:\Users\manoj\Desktop\sandhinaad\ml
pip install numpy pandas scikit-learn joblib matplotlib scipy
python synth_data.py --output data/synthetic_dataset.csv
python train.py --data data/synthetic_dataset.csv --output-dir models/ --report-dir reports/
python export_c_header.py        # writes ../firmware/SandhiNaad/model.h
```
Then re-upload the firmware (step 2). The UI reads the new `models/*.joblib` automatically. After boot, `SELFTEST ... PASS` confirms that the C and Python outputs agree within 1e-4.

When you have real recordings, build the training CSV from `sessions/*/cycles.csv`. The `in_*` columns are exactly the 22 model inputs, in the right order.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Could not open COMx" | Close Serial Monitor, Cura, or any other app using the port; try another USB cable (some cables are power-only) |
| Connected but nothing plots | Check the Log tab. If it shows no `DEV` lines, check the baud (921600) and Core Debug Level = None, then press the EN (reset) button |
| Mic badges both NOT_ATTACHED | Check SD→GPIO33 and 3V3 power; L/R must be tied (not floating) |
| Mic #1/#2 appear swapped | Harmless. The ESP32 legacy I2S driver can swap L/R slot order, and the firmware auto-picks the live mic |
| IMU angle drifts or jumps | Move each BNO055 in a figure-8 until cal shows 3/3/3/3, then click Calibrate zero |
| CRC errors keep rising | Shorter USB cable, use DEFAULT mode instead of FULL, and make sure the baud matches |
| EMG badge FAULT | Electrodes off or dry. Check the AD8232 SDN pin is tied to 3V3 |


---

## 5. Patient questionnaire + multilingual clinical PDF report

Ported from the OA-NER dashboard (same questions, same report layout, same English/Assamese texts).

1. **Language:** use the selector at the top right (English / অসমীয়া). The questionnaire, tab names, risk tier and report all switch together.
2. **Patient & Questionnaire tab:**
   - Fill in registration, the health worker details (remembered on this computer), history and risk factors, presenting complaint (pain scores, functional difficulties), **red flags**, and the clinical examination.
   - Tick the **consent** box.
   - Any red flag shows a referral banner and forces a *priority referral* in the report.
   - *Use answers as clinical prior* feeds age, sex, BMI, occupation and pain/function into the prior model shown on the Screening tab. KOOS is approximated from the NRS pain and difficulty answers.
3. Record the knee with slow, full bends (at least 3 valid cycles).
4. **Clinical Report (PDF) tab:**
   - *Save current result → Right knee*. Then move the sensor to the other knee, do the bends, and click *Save current result → Left knee*. Skip this if you only test one knee; the live session is used for the knee chosen in the exam section.
   - *Export PDF…* writes the report in the chosen language. *Export EN + AS PDFs* writes both into `host/sessions/reports/`.
   - The preview updates automatically.
5. What the report contains:
   - Every value comes from the questionnaire or the measured valid cycles. The tier is the median of the valid cycles.
   - Confidence depends on the number of cycles and their spread.
   - QC fails with fewer than 3 cycles or any link errors.
   - Top signals are the three largest model contributions in plain language.
   - Sessions recorded on the **SIMULATOR** port carry a *SIMULATED DATA* watermark.
6. Command-line samples (no GUI): `python make_report.py --lang as --variant moderate --out sample_as.pdf`

Assamese strings added for SandhiNaad (in `host/reports/i18n/as.json` and `host/i18n/as.json`) should be reviewed by a native speaker before clinical use. Run `python reports/check_i18n.py` to verify both languages have the same keys.
