# Backlog

## Firmware

### Fix stimulation phase for 2-electrode system

**Priority:** High — current behaviour is clinically incorrect for the deployed hardware.

**Problem:**  
The current algorithm fires at both π/2 and 3π/2 (i.e. at every zero-crossing of the tremor cycle). This is appropriate for a dual-channel 4-electrode setup where the two channels fire in antiphase. For the current single-channel 2-electrode system it is wrong — it stimulates twice per tremor cycle instead of once, which disrupts rather than reinforces the intended phase-lock.

**Required change (easy part):**  
Fire at only one of the two zero-crossings per tremor cycle.

**Open question (hard part):**  
Which phase (π/2 or 3π/2) is the therapeutically correct one?  
This depends on:
- **Which arm** is being treated (left vs. right) — the tremor axis is mirrored.
- **Sensor orientation** — the IMU can be mounted in different rotations on the device, which affects the sign of the detected zero-crossing.
- **Biomechanics** — stimulation must fire at the moment the arm is at its closest point to the body during the tremor cycle, so that the evoked nerve response arrives at the thalamus at the right phase to suppress the tremor loop.

**Planned solution — automatic phase detection via gravity vector + arm side:**

The BNO055 already provides the gravity vector at all times, which gives a reliable absolute UP/DOWN reference. Combined with a user-selected Left/Right arm setting in the companion app, the following derivation becomes possible:

1. **Gravity vector → UP/DOWN axis** (always available from the BNO055 in NDOF mode, unambiguous).
2. **Arm side (Left/Right) → mirror the anatomical axis** — the tremor rotation axis is mirrored between arms.
3. **Dominant tremor axis (already tracked by firmware) + gravity + arm side → which direction of rotation corresponds to "arm moving toward body."**
4. **"Toward body" direction → select the correct zero-crossing** (π/2 or 3π/2) as the stimulation trigger.

This approach is sound in principle. Two constraints must be documented and respected:

> ⚠ **Constraint 1 — Arm posture during calibration:**  
> Gravity is vertical. "Toward the body" is roughly horizontal, so gravity alone cannot resolve the toward/away-from-body direction without knowing the patient's arm posture. The derivation requires a defined posture: the arm should be held extended forward at approximately waist height during the phase-detection calibration step. This is a reasonable clinical assumption (tremor is typically assessed in a functional extended posture) but must be communicated to the user.

> ⚠ **Constraint 2 — Sensor placement must be consistent:**  
> The gravity vector tells you UP/DOWN of the sensor, but not whether the sensor is on the dorsal (back), ventral (palm-side), or lateral side of the forearm. A rotation of the device around the forearm's long axis changes the sign of the gravity projection onto the tremor axis. **The device must always be placed on the dorsal (back) side of the forearm.** This must be specified in the electrode placement guide and enforced by convention.

**What needs to be built:**

- **Companion app (Settings screen):** Add "Left arm / Right arm" selector. Transmitted to the device over BLE or stored as a config parameter the firmware reads.
- **Firmware (`tremor_detection.py`):** On lock-in, read gravity vector + arm-side config, project gravity onto the detected tremor axis, and select the zero-crossing polarity that corresponds to the arm moving toward the body. No calibration gesture needed if both constraints above are met.
- **Fallback / validation:** Solution 2 (auto-calibration by amplitude comparison at both phases over N cycles) can serve as an independent cross-check or fallback if the gravity-based derivation is uncertain.

---

### Auto-detect left/right arm at startup via calibration posture

**Idea:** Instead of requiring the user to select left/right in the app, the device can detect which arm it is on at startup using a defined calibration posture and the gravity vector.

**Calibration posture:**  
The patient places both hands in front of them with thumbs pointing toward each other and little fingers pointing downward — the wrist is held at approximately 45° diagonal (thumb side higher). The sensor is always mounted on the dorsal (back) of the wrist with the marked end pointing toward the hand. In this posture, the sign of the lateral gravity component (across the wrist, perpendicular to the forearm axis) is opposite for the left and right hand due to bilateral body symmetry.

**Detection logic:**
1. At startup, the device enters a calibration window (e.g., 3 seconds) — indicated by a pulsing white LED meaning "assume calibration posture."
2. At the end of the window, the firmware reads the gravity vector projected onto the sensor's lateral axis.
3. If the lateral component exceeds a confidence threshold: positive → right arm (cyan LED), negative → left arm (yellow LED).
4. If the lateral component is below the threshold (wrist too flat, posture not assumed): red flashing LED → repeat.
5. The detected arm side is stored in memory and held until the next restart.

**Why this works:**  
The calibration posture constrains both roll ("little finger down") and yaw ("thumb toward midline"). These two constraints on a 3D gravity vector uniquely resolve the left/right ambiguity. The sign of the lateral component is stable across a wide range of "diagonal" angles — the patient does not need to be precise about the exact tilt angle, only that it is clearly non-zero.

**Known issues and constraints:**

> ⚠ **Critical: do NOT read at hard power-on.** The patient needs a few seconds to assume the posture after switching the device on. A startup delay with a visual cue (pulsing white LED) is mandatory — this is the single most failure-prone aspect of the approach.

> ⚠ **Sensor placement mark must be unambiguous.** "Pointing toward the hand" needs a clear physical mark on the device and a diagram in the manual. Misplacement inverts the detection.

> ⚠ **Posture instruction must specify tilt direction.** "Diagonal" is too vague. Instructions must say: "tilt the wrist so the thumb side is higher than the little-finger side, approximately 45 degrees."

> ⚠ **Bilateral tremor / limited mobility.** The posture requires both hands to be free momentarily. This may be difficult for some patients. The app's manual left/right selector should remain as a fallback.

**What needs to be built:**
- **Firmware:** Startup calibration window state, gravity lateral-component sign detection, confidence threshold, LED colour coding (white pulse → cyan/yellow/red).
- **Companion app:** Status indicator showing the detected arm side (e.g., "Right arm detected" in a status bar, with the LED colour). Manual override selector in Settings as fallback.
- **Docs / Help screen:** Calibration posture diagram and step-by-step instructions. Sensor placement diagram with the directional mark clearly shown.

**References:**  
See `docs/SES_Clinical_Reference.md` for the neurophysiology of phase-locked stimulation and the importance of stimulation timing relative to the tremor cycle.

---

## Specification Planning

The items above ("Fix stimulation phase" + "Auto-detect arm side") form a single coherent feature that is best delivered in **two sequential specs**:

- **Spec A — Arm-side detection and communication** (device detects and communicates left/right; app displays and can override)
- **Spec B — Phase-correct stimulation** (firmware uses detected arm side + gravity to select the correct firing zero-crossing)

Spec B depends on Spec A being complete and validated. Spec A can be tested independently by verifying the LED colours and the app status display without changing the stimulation logic at all.

---

### Spec A: Arm-Side Detection

#### User Story

> As a patient with Essential Tremor, I want the device to automatically know which arm I am wearing it on, so that I do not have to configure anything before starting a session. I want a clear visual confirmation from the device and from the companion app, and I want to be able to correct it manually if the detection was wrong.

#### Acceptance Criteria

1. After power-on, the device signals the patient to assume a calibration posture (white pulsing LED for 4 seconds).
2. At the end of the window, the device detects left or right arm from the gravity vector with ≥ 95% reliability when the posture instructions are followed.
3. Detection result is signalled immediately by LED colour: **cyan = right arm, yellow = left arm**.
4. If the gravity reading is ambiguous (magnitude of lateral component below threshold), the device signals failure (rapidly flashing red LED, 2 seconds), then restarts the calibration window automatically once.
5. After a second failed attempt, the device defaults to a "unknown / manual" state (orange steady LED) and continues to startup without arm-side data; the app shows a manual override prompt.
6. The detected arm side is transmitted to the companion app over BLE as part of the telemetry or a dedicated characteristic, and displayed in the app's start screen status bar.
7. The detected arm side persists until the device is restarted.
8. The companion app Settings screen provides a manual left/right override that takes precedence over the detected value.
9. The manual and Help screen contain a calibration posture diagram with step-by-step instructions.

#### Functional Requirements — Firmware

| ID | Requirement |
|----|-------------|
| FW-A1 | On power-on, initialise BNO055 and enter `CALIBRATING` state before any other state. |
| FW-A2 | In `CALIBRATING` state, pulse NeoPixel white (on 200 ms, off 200 ms) for a configurable wait period (`CALIBRATION_WAIT_S`, default 4 s) to allow the patient to assume the posture. |
| FW-A3 | At end of wait period, sample the BNO055 gravity vector. Average 10 samples over 500 ms to reduce noise. |
| FW-A4 | Project the gravity vector onto the sensor's lateral axis (the axis perpendicular to both the forearm long axis and the dorsal normal — i.e. the axis pointing from ulnar to radial side when sensor is dorsal). |
| FW-A5 | If the lateral component magnitude exceeds `LATERAL_THRESHOLD` (default 2.0 m/s²): sign > 0 → RIGHT arm; sign < 0 → LEFT arm. Store result in `arm_side` variable. |
| FW-A6 | If lateral component magnitude ≤ `LATERAL_THRESHOLD`: flash red LED for 2 s, increment `calibration_attempts` counter, repeat from FW-A2 if `calibration_attempts < 2`. |
| FW-A7 | After 2 failed attempts: set `arm_side = UNKNOWN`, set NeoPixel to steady orange, proceed to normal startup. |
| FW-A8 | On successful detection: show cyan (right) or yellow (left) for 2 s, then proceed to normal startup (`UNLOCKED` state). |
| FW-A9 | Include `arm_side` (0 = unknown, 1 = left, 2 = right) in the BLE telemetry packet. This requires extending the packet format (see Spec B for full packet update). |
| FW-A10 | `arm_side` is reset to UNKNOWN on every power cycle. It is never stored in non-volatile memory. |

#### Functional Requirements — Companion App

| ID | Requirement |
|----|-------------|
| APP-A1 | The start screen status bar (currently showing connection dot + "Not connected / Connected") shall also show the detected arm side once connected: "Right arm" / "Left arm" / "Arm unknown". |
| APP-A2 | The arm-side indicator uses a coloured badge matching the device LED: cyan chip for right, yellow chip for left, grey for unknown. |
| APP-A3 | Settings screen gains a "Arm side override" field: a three-way selector (Auto / Left / Right). Default: Auto. When set to Left or Right, this value is sent to the device over BLE and overrides `arm_side` in firmware. |
| APP-A4 | When arm side is UNKNOWN and the device is connected, the app displays a non-blocking banner: "Arm side not detected — restart device or set manually in Settings." |
| APP-A5 | The arm-side value is included in exported session JSON under `session.armSide`. |
| APP-A6 | Help screen gains a "Startup calibration" section with the posture diagram and step-by-step instructions (see Documentation requirements below). |

#### LED State Table — Startup Sequence

| Phase | LED | Duration | Meaning |
|-------|-----|----------|---------|
| Calibration window | White, pulsing (200 ms on/off) | 4 s | "Assume calibration posture now" |
| Reading in progress | White, steady | 0.5 s | Sampling gravity |
| Right arm detected | Cyan, steady | 2 s | Confirmed right arm |
| Left arm detected | Yellow, steady | 2 s | Confirmed left arm |
| Ambiguous reading | Red, fast flash (100 ms) | 2 s | "Posture not recognised — try again" |
| Second failure / unknown | Orange, steady | Until restart | "Could not detect — check app" |
| Normal operation (after detection) | Per existing state machine | — | Unlocked / Locking / Locked / Holdover colours unchanged |

#### BLE Packet Extension

Current packet: 13 bytes. Add 1 byte for `arm_side` at byte 13.

| Byte | Field | Type | Values |
|------|-------|------|--------|
| 13 | `arm_side` | uint8 | 0 = unknown, 1 = left, 2 = right |

Total packet: 14 bytes. Web app decoder must be updated to read byte 13.

#### Documentation Requirements

| Item | Location | Content |
|------|----------|---------|
| Calibration posture diagram | Help screen + Manual | Illustration showing both hands with thumbs toward each other, little fingers down, sensor mark pointing toward hand. Show the ≈45° diagonal tilt with thumb side higher. |
| Step-by-step startup instructions | Help screen + Manual | 1. Put on device (dorsal side, mark toward hand). 2. Switch on — white light pulses. 3. Bring both hands in front of you, thumbs toward each other, little fingers down. Tilt thumbs slightly higher. Hold still. 4. Wait for cyan (right) or yellow (left). 5. If red flashes: repeat step 3. 6. If orange: open app and set arm side manually in Settings. |
| Sensor placement mark description | Manual | Describe/illustrate the physical mark on the device and the "mark toward hand" placement rule. |
| App status bar description | Help screen | Explain the cyan/yellow/grey arm-side chip in the status bar and how to use the manual override in Settings. |

#### Open Questions / Decisions Needed Before Implementation

- [ ] Exact value of `LATERAL_THRESHOLD` — needs empirical testing with real device on different subjects. Suggested starting point: 2.0 m/s² (≈ sin(12°) × g, meaning any tilt > ~12° from vertical is accepted).
- [ ] Should the calibration window length (4 s) be configurable from the app? Probably yes for future tuning.
- [ ] Does the BLE characteristic for the override (app → device) reuse an existing writable characteristic or need a new one?
- [ ] LED colours: cyan and yellow chosen for distinctiveness from existing state colours (blue = unlocked, yellow = locking, off = locked). Confirm no conflict with existing state colour scheme.

---

### Spec B: Phase-Correct Stimulation

#### User Story

> As a patient, I want the device to fire stimulation pulses at the single correct moment in each tremor cycle — when my arm is closest to my body — so that the therapy is maximally effective and does not accidentally reinforce the tremor.

#### Acceptance Criteria

1. For a correctly calibrated device (arm side known, sensor placement correct), stimulation fires exactly once per tremor cycle.
2. The firing moment corresponds to the zero-crossing of angular velocity at which the arm is moving toward the body (not away from it).
3. Behaviour is correct for both left and right arm.
4. If arm side is UNKNOWN, the device falls back to firing at both zero-crossings (current behaviour) and the app displays a warning.
5. The phase selection logic is derived automatically from the gravity vector and arm side — no manual phase parameter is needed in normal operation.
6. A manual phase override (0 = auto, 1 = force π/2, 2 = force 3π/2) is available in the app Settings for diagnostic and research purposes.

#### Functional Requirements — Firmware

| ID | Requirement |
|----|-------------|
| FW-B1 | After transitioning to `LOCKING` state, if `arm_side` is known, compute the preferred zero-crossing polarity: project the gravity vector onto the plane perpendicular to the detected tremor axis; use arm side to resolve the rotational direction that corresponds to "toward body." |
| FW-B2 | Store the result as `fire_polarity` (+ or −). In `LOCKED` state, only trigger stimulation at zero-crossings that match `fire_polarity`. |
| FW-B3 | If `arm_side == UNKNOWN`, set `fire_polarity = BOTH` (current behaviour). Log this in the BLE telemetry. |
| FW-B4 | If the app sends a manual phase override (see APP-B2), use that value in place of the computed polarity. |
| FW-B5 | The stimulation count in telemetry should now increment once per tremor cycle (not twice). The app's session review should reflect this. |
| FW-B6 | Include `fire_polarity` (0 = both, 1 = π/2, 2 = 3π/2) in BLE telemetry packet (byte 14, extending packet to 15 bytes). |

#### Functional Requirements — Companion App

| ID | Requirement |
|----|-------------|
| APP-B1 | If `arm_side == UNKNOWN` and device is LOCKED, show a persistent warning on the recording screen: "Arm side unknown — stimulation may be firing at wrong phase. Restart device or set arm side in Settings." |
| APP-B2 | Settings screen gains a "Stimulation phase override" field: Auto / Force π/2 / Force 3π/2. Default: Auto. For diagnostic and research use only — label it accordingly. |
| APP-B3 | Session export JSON includes `firePolarity` field under session metadata. |
| APP-B4 | Recording screen metrics card shows detected arm side and active fire polarity as small read-only status fields. |

#### Dependencies

- Spec B cannot be started until Spec A is complete and the `arm_side` value is reliably available in firmware.
- Spec B requires the BLE packet to be extended (14 → 15 bytes). Both firmware and app decoder must be updated together.
- Spec B requires the arm-side biomechanics derivation to be validated empirically on at least one subject before shipping: confirm that the computed polarity actually reduces tremor (not increases it). The amplitude-comparison fallback (try both phases, keep the better one) should be implemented as a safety net.

#### Open Questions / Decisions Needed Before Implementation

- [ ] Validate the gravity-projection math on paper and with a physical prototype before coding. Document the exact coordinate frame convention for the BNO055 axes vs. the anatomical axes.
- [ ] Define "toward body" precisely: is it the inward swing (adduction) or the downward swing (flexion)? Depends on the patient's tremor type and typical arm position. May need to be validated per-patient in early trials.
- [ ] Amplitude-comparison fallback: how many cycles to test each phase? Suggested: 10 cycles per phase (≈ 2–5 seconds at typical tremor frequencies). Define the comparison metric (peak magnitude, RMS, or frequency spread).
- [ ] Does the stimulation count metric in the app need to be relabelled now that it increments once per cycle instead of twice?
