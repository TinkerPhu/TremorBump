# Backlog

---

## Main Goal

The current firmware fires a stimulation burst at **every** zero-crossing of the detected tremor angular velocity — i.e. at both π/2 and 3π/2 per cycle. This made sense as a placeholder and is correct for a future dual-channel 4-electrode system where the two channels fire in antiphase. For the current **single-channel 2-electrode system it is clinically wrong**: it stimulates twice per tremor cycle, which disrupts the phase-lock rather than reinforcing it.

**The goal of all three features below is to make the device fire at exactly one zero-crossing per tremor cycle — the one where the arm is moving closest to the body — and to determine that zero-crossing automatically from the sensor data and a one-time arm-side configuration.**

The three features must be delivered in order. Each is independently testable.

---

## Feature 1 (Prerequisite): BLE Settings Characteristic

### Goal

Allow the companion app to read and write persistent device settings over BLE. This is the communication layer that all subsequent features depend on. Nothing else in this backlog can be built without it.

### Context

The existing BLE GATT service (`7f6d0001`) has one characteristic:
- `7f6d0002` — telemetry, **notify + read**, device → app, currently 13 bytes.

A second characteristic must be added to the same service:
- `7f6d0003` — settings, **read + write**, bidirectional, 8-byte versioned struct.

### Settings Struct v1

All bytes little-endian. Total: 8 bytes (fits in one BLE write packet).

| Byte | Field | Type | Values | Default |
|------|-------|------|--------|---------|
| 0 | `struct_version` | uint8 | 1 | 1 |
| 1 | `arm_side` | uint8 | 0 = not set, 1 = left, 2 = right | 0 |
| 2 | `calibration_wait_s` | uint8 | 1–10 | 4 |
| 3 | `lateral_threshold_x10` | uint8 | 1–50 (= 0.1–5.0 m/s²) | 20 |
| 4 | `fire_polarity_override` | uint8 | 0 = auto, 1 = positive crossing, 2 = negative crossing | 0 |
| 5–7 | *(reserved)* | uint8 × 3 | 0xFF | 0xFF |

`struct_version` must be incremented whenever the layout changes. App and firmware both check it and handle mismatches gracefully.

### App ↔ Device Protocol

**On every BLE connection (before Settings screen is usable):**
```
App connects
  → Read 7f6d0003 (8 bytes)
  → Check struct_version
      - Unknown version (device newer than app): show notice, disable writes, show read-only values
      - Known version: update Settings UI, cache struct in session memory
```

**On every user-initiated setting change:**
```
User changes value in Settings screen
  → Merge change into cached struct (never build struct from UI state alone)
  → Write full 8-byte struct to 7f6d0003 (write-with-response)
  → Wait 300 ms
  → Read back 7f6d0003
  → Compare: match → show "Saved"; mismatch → show error, revert UI to read-back value
```

**Settings are never stored in the app's localStorage or IndexedDB. The device NVM is the single source of truth. The app always reads from the device on connect.**

### Firmware Implementation Plan (`ble_telemetry.py`)

- Add `7f6d0003` characteristic to the existing GATT service definition with read + write-with-response permissions.
- On **read**: assemble 8-byte struct from `microcontroller.nvm[0:8]`. If any NVM byte is 0xFF (uninitialised), substitute the field's default value before returning.
- On **write**: validate `struct_version` matches firmware's expected version — reject silently if not. Validate each field is within allowed range — clamp out-of-range values. Write validated fields to `microcontroller.nvm[0:8]`. Apply any field that takes immediate effect (see Feature 2 for `arm_side`). Flash LED to confirm.
- Reserve `microcontroller.nvm[0:8]` exclusively for this struct. Any future NVM use starts at index 8.

### Companion App Implementation Plan (`tremor_recorder.html`)

- On BLE connect, read `7f6d0003` immediately. Settings screen shows a spinner until read completes.
- Cache read result in a session-scoped JS object `deviceSettings`. All writes merge into this object.
- Settings screen gains a new "Device settings" section (separate from the existing app-local aggregate interval / stim-window settings, which remain in localStorage):
  - **Arm side**: Left / Right / Not set (three-way, maps to 1/2/0)
  - **Calibration window**: slider 1–10 s (advanced, collapsible)
  - **Phase override**: Auto / Force positive / Force negative (diagnostic, collapsible, labelled "research use only")
- Write → read-back → confirm / error as per protocol above.
- On BLE disconnect during a write in progress: show error, re-read on reconnect before enabling further writes.

### Documentation Plan

- `docs/` or inline in app Help: explain that "Device settings" are stored on the device, survive power cycles, and are separate from app-local session settings.

### Open Questions

- [ ] 300 ms read-back delay: verify empirically that `microcontroller.nvm` write completes within this window on the QT Py ESP32-S3.
- [ ] Write-with-response is recommended. Confirm CircuitPython's `adafruit_ble` supports it on the server (peripheral) side.
- [ ] Security: no write protection planned for now given niche use case. Revisit if device is used in a clinical setting.

---

## Feature 2: Arm-Side Configuration and Detection

### Goal

The device must know which arm it is on (left or right) so that Feature 3 can select the correct stimulation phase. This feature stores the arm side persistently in NVM, communicates it via BLE, confirms it with the LED, and provides a gravity-vector auto-detection fallback for first-time setup.

### User Story

> As a patient or carer, I want to configure which arm the device is worn on once — and have the device remember it forever after — so I never have to think about it again. I want a clear visual confirmation that the setting is correct every time I switch the device on.

### Primary Mechanism: App Sets NVM via BLE Settings Characteristic

This is the default workflow:

1. Patient (or carer) connects the companion app.
2. Opens Settings → selects Left or Right arm.
3. App writes `arm_side` field to the device via `7f6d0003`.
4. Firmware writes to NVM and flashes LED confirmation (cyan = right, magenta = left).
5. On every subsequent power-on, device reads NVM, knows arm side, shows LED confirmation for 1 second, proceeds to normal operation.

No calibration posture. No timing windows. No ambiguity.

### Fallback Mechanism: Gravity Auto-Detection (First Boot / NVM Empty)

If NVM byte 1 is 0 (never configured), the device runs a one-time gravity-based detection at startup:

**Calibration posture:**  
Patient holds both arms in front with thumbs pointing toward each other and little fingers pointing downward — wrist tilted approximately 45° diagonal with thumb side higher. Sensor always on the dorsal (back) of the wrist, marked end toward the hand.

In this posture the sign of the gravity vector's lateral component (across the wrist, perpendicular to the forearm long axis) is opposite for left and right arm due to bilateral body symmetry.

**Detection:**
1. White pulsing LED (200 ms on/off) for `calibration_wait_s` (default 4 s) — "assume posture now."
2. Sample gravity vector, average 10 readings over 500 ms.
3. Project onto sensor lateral axis.
4. If magnitude > `lateral_threshold_x10 / 10` m/s²: sign → arm side. Write NVM. Show LED 2 s.
5. If magnitude ≤ threshold: flash red 2 s, retry once. After second failure: `arm_side = UNKNOWN`, steady orange LED, continue without writing NVM.

**This auto-detection only runs when NVM is empty.** On all subsequent boots the NVM value is used. The fallback is only ever encountered on first use or after an explicit NVM reset.

### Startup Boot Sequence

```
Power on
  │
  ▼
Read microcontroller.nvm[1] (arm_side field)
  │
  ├─ 1 or 2 ──► Flash cyan (right) or magenta (left) 1 s ──► Normal operation
  │
  └─ 0 (not set) ──► White pulse 4 s (assume posture)
                        │
                        ├─ Gravity OK ──► Write NVM ──► Flash cyan/magenta 2 s ──► Normal operation
                        │
                        └─ Fail × 2 ──► Orange steady ──► arm_side = UNKNOWN ──► Normal operation
```

### LED Colour Assignment

| Event | Colour | Duration | Notes |
|-------|--------|----------|-------|
| Calibration window | White, pulsing 200/200 ms | 4 s | "Assume posture" |
| Sampling | White, steady | 0.5 s | Reading gravity |
| Right arm confirmed | Cyan | 1–2 s | Does not conflict with any run-time state |
| Left arm confirmed | Magenta | 1–2 s | Does not conflict with any run-time state |
| Ambiguous reading | Red, fast 100 ms | 2 s | "Try again" |
| Unknown / failed | Orange, steady | Until next event | "Set manually in app" |

> ⚠ **Yellow is NOT used for left arm.** Yellow is already the LOCKING state colour in normal operation. Magenta is used instead to avoid confusion, even though the startup sequence and normal operation are temporally separate.

Existing run-time NeoPixel colours (unchanged):

| State | Colour |
|-------|--------|
| UNLOCKED | Blue |
| LOCKING | Yellow |
| LOCKED | Off |
| HOLDOVER | Off (brief burst flashes on stimulation) |

### Telemetry Packet Extension

Add byte 13 to the existing notify packet:

| Byte | Field | Type | Values |
|------|-------|------|--------|
| 13 | `arm_side` | uint8 | 0 = unknown, 1 = left, 2 = right |

Total: 14 bytes. App decoder must be updated.

### Firmware Implementation Plan (`ble_telemetry.py` + `tremor_detection.py`)

- `ble_telemetry.py`: add byte 13 to the notify packet struct. Populate from `arm_side` variable maintained by tremor_detection.
- `tremor_detection.py`: on startup, read `microcontroller.nvm[1]`. Branch to NVM path or gravity-detect path. Maintain `arm_side` variable accessible to BLE module. Handle BLE settings write for `arm_side` field: validate, write NVM, update RAM variable, flash LED.

### Companion App Implementation Plan

- Start screen status bar: show arm-side chip alongside connection status. Cyan = right, magenta = left, grey = unknown.
- When `arm_side == UNKNOWN` and connected: non-blocking warning banner "Arm side unknown — set in Settings or restart device."
- Settings screen "Device settings" section (from Feature 1): arm-side selector as described.
- Session export JSON: add `armSide` field to session metadata.
- Recording screen metrics card: small read-only "Arm side" and "Phase" fields (populated from telemetry bytes 13 and 14 once Feature 3 is done).

### Documentation Plan

- Help screen: add "Startup — arm side" section. Explain both paths (set in app = recommended; auto-detect on first boot). Include:
  - Calibration posture diagram (both hands, thumbs toward each other, little fingers down, ~45° tilt, sensor mark toward hand).
  - 6-step startup instructions (see below).
  - Sensor placement diagram: dorsal side, mark toward hand.
  - Description of the LED colours and what they mean.
- Manual (`docs/Manual_electrode_placement.md`): add sensor placement section describing the dorsal placement rule and the directional mark. This is a hard constraint: **if the sensor is not on the dorsal side, the gravity detection inverts**.
- `docs/` or inline README: document the NVM byte layout.

**Step-by-step startup instructions (first use, NVM empty):**
1. Put the device on (dorsal side of wrist, marked end toward hand).
2. Switch on — LED pulses white. You have ~4 seconds.
3. Hold both hands in front of you: thumbs pointing toward each other, little fingers pointing down. Tilt so your thumbs are slightly higher than your little fingers.
4. Hold still until the LED changes.
5. Cyan = right arm, magenta = left arm. If correct: wait for normal startup.
6. If LED flashes red: the posture was not clear enough. Repeat step 3.
7. If LED stays orange: posture could not be detected. Open the companion app → Settings → set arm side manually.

### Open Questions

- [ ] `LATERAL_THRESHOLD` default 2.0 m/s² (≈ sin(12°) × 9.81): verify empirically with the physical prototype. A tilt of 12° or more is sufficient — the posture instruction calls for ~45°, so this gives large margin.
- [ ] Calibration window duration (4 s) should be configurable from app (`calibration_wait_s` in settings struct). Confirm this is included in Feature 1 struct.
- [ ] NVM byte index: Feature 1 defines `microcontroller.nvm[0]` as `struct_version` and `nvm[1]` as `arm_side`. Confirm that the startup read uses `nvm[1]` (not `nvm[0]` as written in some earlier notes — that was a draft error).
- [ ] "Re-detect" command from app: implement as writing `arm_side = 0` to the settings characteristic. Device writes 0 to NVM. On next power cycle the gravity path runs again. No special command needed.

---

## Feature 3: Phase-Correct Stimulation (Single Phase per Cycle)

### Goal

This is the main goal of the entire backlog. Once the arm side is known (Feature 2), the firmware derives the correct zero-crossing polarity (positive or negative) to use as the stimulation trigger, and fires **once per tremor cycle** at that crossing. The result is a properly phase-locked single-channel SES therapy.

### User Story

> As a patient, I want the device to fire one stimulation pulse per tremor cycle — at the moment my arm is moving closest to my body — so that the therapy correctly interrupts the tremor feedback loop instead of accidentally reinforcing it.

### Acceptance Criteria

1. With arm side known and sensor correctly placed (dorsal, mark toward hand), stimulation fires exactly once per tremor cycle.
2. The firing zero-crossing corresponds to the arm moving toward the body.
3. Behaviour is mirrored correctly for left vs. right arm.
4. If arm side is UNKNOWN: device falls back to firing at both zero-crossings (current behaviour) and app shows a warning on the recording screen.
5. The phase can be overridden manually from the app Settings (research/diagnostic use only).
6. Stimulation count in telemetry increments once per cycle (previously twice).

### Phase Selection Logic

The BNO055 gyroscope measures angular velocity in its own sensor frame. The firmware already identifies the dominant tremor axis as a 3D unit vector. The angular velocity projected onto this axis oscillates at the tremor frequency; zero-crossings mark the turning points of the tremor cycle.

The two zero-crossings per cycle are:
- **Positive-going** (velocity crosses zero from negative to positive): arm reverses direction one way.
- **Negative-going** (velocity crosses zero from positive to negative): arm reverses direction the other way.

Which one corresponds to "arm moving toward body" depends on:
1. **Gravity vector**: tells us the orientation of the sensor in 3D space (up/down unambiguous).
2. **Arm side (left/right)**: mirrors the anatomical axis — on the right arm, "toward body" is a leftward rotation; on the left arm it is rightward.
3. **Sensor placement constraint**: sensor must be on the dorsal side — this fixes the sign convention between the sensor's lateral axis and the anatomical rotation direction.

> ⚠ **Constraint — arm posture for phase computation:**  
> The gravity vector resolves up/down. "Toward the body" is a roughly horizontal direction. For the derivation to work, the arm must be approximately horizontal (extended forward or to the side) during lock-in, so that the gravity-projected component on the tremor axis is informative. The firmware should compute phase polarity once at the moment of LOCKED transition, using the gravity vector at that instant. If the arm is pointing straight up or down at lock-in, the derivation may be ambiguous — treat this as a degenerate case and fall back to BOTH.

**Derivation steps (to be validated on hardware before coding):**
1. At transition to LOCKED: read gravity vector `g` and dominant tremor axis `t` (both from BNO055 NDOF output).
2. Project `g` onto the plane perpendicular to `t`: `g_perp = g - (g·t)t`. This is the "downward" direction as seen from the tremor axis.
3. The "toward body" rotational direction is the cross product of `t` and `g_perp`, sign-corrected for arm side.
4. Compare this direction to the sign convention of the angular velocity projection. The matching zero-crossing polarity is `fire_polarity`.

### Firmware Implementation Plan (`tremor_detection.py`)

- On transition to `LOCKED` state:
  - If `arm_side == UNKNOWN`: set `fire_polarity = BOTH`. Continue current behaviour.
  - If `arm_side` is known: compute `fire_polarity` using the derivation above.
  - If `fire_polarity_override != 0` (from settings struct): use override value instead.
- In `LOCKED` and `HOLDOVER` states: only call `run_biphasic_burst()` at zero-crossings matching `fire_polarity`. Skip the other crossing.
- Re-compute `fire_polarity` each time the device re-locks (after holdover or re-locking from UNLOCKED). The arm may have moved.
- Include `fire_polarity` (0 = both, 1 = positive crossing, 2 = negative crossing) as byte 14 in the telemetry notify packet.

### Telemetry Packet Extension (cumulative)

| Byte | Field | Notes |
|------|-------|-------|
| 0–12 | Existing fields | Unchanged |
| 13 | `arm_side` | Added in Feature 2 |
| 14 | `fire_polarity` | 0 = both (fallback), 1 = positive, 2 = negative |

Total packet: 15 bytes.

### Companion App Implementation Plan

- Update telemetry packet decoder: read byte 14 as `firePolarity`.
- Recording screen: show `armSide` and `firePolarity` as small status fields in the secondary metrics card. Values: "Both (unknown arm)" / "Positive" / "Negative".
- Warning on recording screen if `firePolarity == 0` (both): "Arm side unknown — stimulation firing at both phases. Set arm side in Settings."
- Settings screen "Device settings" → "Phase override" (already planned in Feature 1): Auto / Force positive crossing / Force negative crossing. Labelled "Research / diagnostic use only."
- Session export JSON: add `firePolarity` to session metadata.
- Stimulation count metric: relabel from "Stimulation count" to "Stimulation bursts" (count now increments once per cycle, not twice — no numerical change needed, just a label clarification).

### Documentation Plan

- Help screen: add brief explanation that the device automatically selects the stimulation phase from the sensor data and arm side. No user action required beyond correct arm-side configuration.
- Help screen warning: "If the arm-side indicator shows 'unknown', the device stimulates at both phases, which reduces therapy effectiveness. Set the arm side in Settings."
- Manual: add a technical note on the phase-selection mechanism for clinical reference.

### Dependencies

- Feature 3 cannot start until Feature 2 is complete and `arm_side` is reliably available in firmware.
- BLE packet must be 15 bytes. App decoder and firmware must be updated together.
- **The phase derivation math must be validated on paper and then on the physical device before coding.** Document the exact BNO055 axis convention (X/Y/Z orientation on the sensor chip vs. the anatomical forearm axes) before writing a single line of firmware.

### Open Questions

- [ ] Work out and document the BNO055 coordinate frame: which sensor axis is along the forearm, which is lateral, which is dorsal. This is the foundation of the entire derivation. Get it wrong and the phase is inverted.
- [ ] Define "toward body" precisely for the expected tremor type (Essential Tremor typically involves pronation/supination and flexion/extension of the wrist and forearm). Is the relevant motion adduction or flexion? This may need per-patient validation in early trials.
- [ ] Degenerate case: arm pointing straight up or down at lock-in. Define the ambiguity threshold and the fallback behaviour (fire at both, warn in app).
- [ ] Amplitude-comparison validation: after shipping phase-correct stimulation, add an optional calibration mode where the device fires at each polarity for 10 cycles and reports the tremor amplitude change to the app. This lets a clinician verify that the chosen phase is actually reducing tremor — or flip it if not.
- [ ] Stimulation count relabelling: confirm with any clinical collaborators that relabelling "count" as "bursts" and halving the per-session count is not confusing for session comparison across the old and new firmware.
