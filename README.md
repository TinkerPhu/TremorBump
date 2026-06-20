# Tremor-Synchronized Stimulation Project



> **WARNING — USE ENTIRELY AT YOUR OWN RISK**
> This device applies electrical stimulation to the human body at up to **40 V DC**
> through skin-contact electrodes. Voltages at this level can cause electric shock,
> skin burns, cardiac arrhythmia, or other serious injury, particularly in people
> with cardiac conditions, implanted electronic devices (pacemakers, neurostimulators),
> or broken/damaged skin. There is no medical certification or regulatory approval of
> any kind. You, and you alone, are fully responsible for any harm to yourself or
> others that results from building, modifying, or using this device.
> **Do not use on another person without their explicit, informed consent.**

This project implements a wearable device that detects hand/arm tremor in
real time and delivers phase-locked electrical stimulation in sync with the
tremor cycle, plus a companion web app for recording, reviewing, and
exporting telemetry from the device over Bluetooth Low Energy (BLE).

**KUDOS to the following projects that were the main inspiration:**

- **[DIY Transcutaneous Spinal Stimulator Guide](https://www.scribd.com/document/766706842/An-easy-to-build-transcutaneous-electrical-stimulator-for-spinal-cord-stimulation-therapy)**
- **[OpenVstim](https://github.com/MonzurulAlam/OpenVstim)**

See docs\References.md for more sources.


**It consists of four parts:**

1. **Hardware** — a wearable unit built around the Adafruit QT Py ESP32-S3,
   comprising two subsystems:
   - *Sensing:* an Adafruit BNO055 IMU measures gyroscope and quaternion data
     to detect tremor axis, frequency, and phase in real time.
   - *Stimulation:* a boost converter raises the supply to up to 40 V DC,
     which an H-bridge switches across skin-contact electrodes to deliver
     charge-balanced biphasic pulses synchronized to the tremor cycle.
2. **Tremor detection firmware** (`tremor_detection.py`) — runs on the device,
   detects tremor frequency/axis from the IMU, and drives the H-bridge to
   deliver biphasic stimulation pulses synchronized to the tremor.
3. **BLE telemetry** (`ble_telemetry.py`) — a custom BLE GATT service that
   advertises as `TREMOR` and streams live detector state to nearby devices.
4. **Tremor Recorder web app** (`tremor_recorder.html`) — a single-file,
   offline-capable HTML/JS app (Web Bluetooth + IndexedDB) for pairing with
   the device, recording sessions, charting live/aggregated data, and
   exporting/sharing results.

This is experimental code intended for use on isolated test hardware only.

```
TremorBump/
├── CircuitPython/          # Firmware — copy contents to the CIRCUITPY drive
│   ├── code.py
│   ├── tremor_detection.py
│   ├── ble_telemetry.py
│   ├── settings.toml
│   └── lib/                # Required CircuitPython libraries
├── CompanionApp/
│   └── tremor_recorder.html
└── docs/
    ├── References.md
    └── conductive_electrode_gel_recipe.md
```

## Hardware required

- **Adafruit QT Py ESP32-S3** (4MB Flash / 2MB PSRAM variant,
  board ID `adafruit_qtpy_esp32s3_4mbflash_2mbpsram`). BLE is required, so the
  ESP32-S2 variant (no Bluetooth) will not work.
- **Adafruit BNO055** 9-DOF absolute orientation IMU, connected via I2C
  (`board.SCL` / `board.SDA`), used in NDOF fusion mode for gyro + quaternion
  data.
- **Boost converter** that steps the supply up to as much as **40 V DC**,
  feeding the H-bridge so it can drive the stimulation electrodes at
  therapeutic voltage.
- **H-bridge** driver for the stimulation electrodes, connected to
  `board.MOSI` (h_bridge_1) and `board.MISO` (h_bridge_2), switching the
  boosted 40 V supply to produce the stimulation waveform described below.
- **Stimulation electrodes** with conductive gel for skin contact. A DIY
  saline/glycerin/xanthan gel recipe is provided in
  [`docs/conductive_electrode_gel_recipe.md`](docs/conductive_electrode_gel_recipe.md).
- Onboard **NeoPixel** LED, used to indicate detector state (unlocked /
  locking / locked / holdover) and stimulation polarity.
- A BLE-capable computer or phone with a Chromium-based browser (Chrome /
  Edge) supporting Web Bluetooth, to run `tremor_recorder.html`.

## Firmware: required libraries

CircuitPython **10.2.0** with the following libraries in `lib/`:

- `adafruit_ble` — BLE radio, advertising, GATT services/characteristics
- `adafruit_bno055` — BNO055 IMU driver (gyro + quaternion)
- `adafruit_register` — register access helpers (dependency of the BNO055
  driver)
- `adafruit_pixelbuf` and `neopixel` — onboard NeoPixel status LED

Plus the CircuitPython built-in modules `board`, `busio`, `digitalio`,
`supervisor`, `math`, `time`, and `struct`.

The firmware entry point is `code.py`, which simply does
`import tremor_detection`.

## How tremor detection works (`tremor_detection.py`)

The detector samples the BNO055 gyroscope at **75 Hz** and runs a state
machine with four states:

- **UNLOCKED** — no tremor signal detected yet.
- **LOCKING** — a candidate tremor axis and frequency are being established;
  requires several alternating zero-crossings (4 from cold start, 2 when
  re-locking after holdover) within a timeout.
- **LOCKED** — tremor axis, frequency, and phase are tracked continuously;
  stimulation bursts are scheduled phase-correctly at each detected
  zero-crossing, with dead-reckoning between crossings.
- **HOLDOVER** — if the signal is lost while locked, stimulation continues at
  the last known frequency (at reduced duty cycle) via dead-reckoning for up
  to 5 seconds before falling back to UNLOCKED.

Key processing steps per sample:

1. Remove slowly-adapting gyro DC bias.
2. Optionally rotate gyro readings into world frame using the BNO055
   quaternion, so arm movement doesn't distort the tremor axis estimate.
3. Track the dominant tremor axis with a 3-D direction EWMA (fast time
   constant while locking, slow once locked).
4. Project motion onto that axis and track an amplitude envelope; detect
   hysteretic zero crossings with linear interpolation for precise timing.
5. Estimate tremor frequency (2–8 Hz) from alternating half-periods and use
   it to phase-correct the stimulation schedule.

When a stimulation event fires, `run_biphasic_burst()` drives the H-bridge
with a symmetric biphasic pulse train (250 µs phases, 1 µs interphase gap,
200 Hz internal pulse rate) for a duration proportional to the current tremor
period and a configurable duty cycle (halved during holdover).

### Stimulation waveform

A boost converter raises the device's supply to up to **40 V DC**. The
H-bridge switches this 40 V rail across the wrist electrodes to produce a
**biphasic (alternating-polarity) square-wave pulse train**: each pulse
consists of a 250 µs positive phase, a 1 µs interphase gap, and a 250 µs
negative phase, repeating at an internal pulse rate of 200 Hz. This biphasic
shape keeps the pulses charge-balanced (no net DC component), which is the
standard approach for safe transcutaneous nerve stimulation. Bursts of these
pulses are timed to coincide with the detected tremor cycle (locked) or its
extrapolated continuation (holdover), with a burst duration of
`duty_cycle / tremor_hz` — i.e. a fixed fraction (12.5%, or 6.25% during
holdover) of each tremor period — so the stimulation pulses the wrist nerves
in sync with, and proportional to, the ongoing tremor.

The onboard NeoPixel shows blue (unlocked), yellow (locking), off
(locked/holdover, with brief flashes on each stimulation burst showing
polarity).

## BLE telemetry protocol (`ble_telemetry.py`)

The device advertises as **`TREMOR`** with a custom 128-bit GATT service:

- Service UUID: `7f6d0001-6f7a-4f4e-9a8b-3b7f4b000001`
- Telemetry characteristic UUID: `7f6d0002-6f7a-4f4e-9a8b-3b7f4b000001`
  (read + notify)

The device name is placed in the BLE scan response (not the main
advertisement) so the custom service UUID fits in the primary advertisement
packet, allowing Web Bluetooth to discover the service by UUID.

While connected, the device sends a **13-byte, little-endian notify packet**
at 2 Hz (`BLE_NOTIFY_HZ`):

| Field           | Type   | Notes                                   |
|-----------------|--------|-----------------------------------------|
| `device_t_ms`   | uint32 | raw device milliseconds, wraps ~49 days |
| `state_code`    | uint8  | 0=UNLOCKED 1=LOCKING 2=LOCKED 3=HOLDOVER, 255=unknown |
| `sched_hz_x100` | uint16 | scheduling frequency × 100 (0.01 Hz resolution) |
| `tremor_hz_x100`| uint16 | measured tremor frequency × 100 (0.01 Hz resolution) |
| `mag_env_x10`   | uint16 | 3-D gyro magnitude envelope × 10 (0.1 deg/s resolution) |
| `stim_count`    | uint16 | cumulative stimulation count, wraps at 65535 |

The ESP-IDF BLE stack runs as a background FreeRTOS task, so the connection
stays alive even during the brief (~30 ms) blocking stimulation bursts.

## Tremor Recorder web app (`tremor_recorder.html`)

A single-file, no-build-step, offline-capable web app (HTML + CSS + vanilla
JS) that connects to the `TREMOR` device over Web Bluetooth, records
telemetry sessions, and lets you review/export them. Works on desktop
(Chrome/Edge) and mobile Chrome on Android.

### Pairing & connection

- The device picker is filtered to devices whose advertised name starts with
  `TREMOR`, using `filters: [{ namePrefix: "TREMOR" }]`.
- The GATT connection is kept open across recording sessions (not
  re-paired/torn down after each stop), and silently reconnects if dropped.

### Screens

- **Start** — primary card with status line, a large "Start recording" button
  and a "Sessions" button; secondary card (scroll to reach) with
  Export / Admin / Settings and an optional "Run simulated session" button.
- **Recording** — primary card with large live Magnitude and Tremor frequency
  tiles, a "Stop & save" button, and a status/error line, all fitting on
  screen without scrolling; secondary card (scroll to reach) shows
  Stimulation count, Sched frequency, State, and Samples recorded.
- **Session saved** — large "Start new recording" button (reuses the existing
  BLE connection, or pairs first if needed) plus a summary and a link to
  review the saved session.
- **Review** — shows session summary and two SVG charts (Tremor frequency,
  Magnitude) plotting the per-interval average as a line with the min/max
  range as a shaded band. The Y-axis is scaled to 80%–120% of the average's
  min/max to avoid outlier samples dominating the scale.

### Data storage (IndexedDB: `tremor_recorder_db`)

- `sessions` — one record per recording session (start/stop times, device
  name, disconnect reason, config snapshot, sample count).
- `samples` — one record per telemetry packet received (timestamps, state,
  scheduled/tremor frequency, magnitude, stim count).
- `aggregates` — per-interval (default 10 s, configurable) min/avg/max
  statistics for tremor frequency and magnitude, plus active-stim coverage.

### Export & sharing

- CSV export of raw samples and JSON export of session summaries/aggregates.
- On desktop, both exports download as files.
- On mobile, "Share raw samples (CSV)" and "Share summary (JSON)" open the
  native share sheet (the JSON is shared as a `.txt` file due to Chromium
  share-target restrictions on `.json`/`application/json`).

### Simulation mode

Appending `?simulate=1` to the URL enables a "Run simulated session" button
that generates synthetic telemetry without requiring a real device — useful
for UI testing.
