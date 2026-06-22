# Backlog

---

## Main Goal

The current firmware fires a stimulation burst at **every** zero-crossing of the detected tremor angular velocity — i.e. at both π/2 and 3π/2 per cycle. This made sense as a placeholder and is correct for a future dual-channel 4-electrode system where the two channels fire in antiphase. For the current **single-channel 2-electrode system it is clinically wrong**: it stimulates twice per tremor cycle, which disrupts the phase-lock rather than reinforcing it.

**The goal of all three features below is to make the device fire at exactly one zero-crossing per tremor cycle — the one where the arm is moving closest to the body — and to determine that zero-crossing automatically from the sensor data and a one-time arm-side configuration set in the companion app.**

If arm side is not configured, the device does **not** stimulate at all. There is no automatic detection, no fallback to both phases, and no ambiguous state. The companion app is the right place to set and confirm arm side.

The three features must be delivered in order. Each is independently testable.

---

## Feature 1 (Prerequisite): BLE Settings Characteristic

### Goal

Allow the companion app to read and write persistent device settings over BLE. This is the communication layer that all subsequent features depend on. Nothing else in this backlog can be built without it.

### Context

The existing BLE GATT service (`7f6d0001`) has one characteristic:
- `7f6d0002` — telemetry, **notify + read**, device → app, 13 bytes (unchanged).

A second characteristic is added to the same service:
- `7f6d0003` — settings, **read + write**, bidirectional, 8-byte versioned struct.

The telemetry packet is **not** extended. Settings are read once on connect and trusted for the duration of the session. The session record stores the settings bytes as a header so every recording is self-describing.

### Settings Struct v1

All bytes little-endian. Total: 8 bytes.

| Byte | Field | Type | Values | Default |
|------|-------|------|--------|---------|
| 0 | `struct_version` | uint8 | 1 | 1 |
| 1 | `arm_side` | uint8 | 0 = not set, 1 = left, 2 = right | 0 |
| 2 | `fire_polarity_override` | uint8 | 0 = auto, 1 = positive crossing, 2 = negative crossing | 0 |
| 3–7 | *(reserved)* | uint8 × 5 | 0xFF | 0xFF |

`struct_version` must be incremented whenever the layout changes. App and firmware both check it and handle mismatches gracefully.

### App ↔ Device Protocol

**On every BLE connection (before Settings screen is usable):**
```
App connects
  → Read 7f6d0003 (8 bytes)
  → Check struct_version
      - Unknown version (device newer than app): show notice, disable writes, show read-only values
      - Known version: update Settings UI, cache struct in session memory as deviceSettings
```

**On every user-initiated setting change:**
```
User changes value in Settings screen
  → Merge change into cached deviceSettings struct (never build struct from UI state alone)
  → Write full 8-byte struct to 7f6d0003 (write-with-response)
  → Wait 300 ms
  → Read back 7f6d0003
  → Compare: match → show "Saved"; mismatch → show error, revert UI to read-back value
```

**Settings are never stored in the app's localStorage or IndexedDB. The device NVM is the single source of truth. The app always reads from the device on connect.**

### Session Data Header

When a session starts, the app reads the current `deviceSettings` object (already cached from connect-time read) and stores it as part of the session record in IndexedDB:

```
session.deviceSettings = {
  structVersion: 1,
  armSide: 1,          // 0 = not set, 1 = left, 2 = right
  firePolarityOverride: 0,
  rawBytes: [1, 1, 0, 255, 255, 255, 255, 255]  // full 8-byte struct as recorded
}
```

This is included in every JSON export under `session.deviceSettings`. It means any recording is fully self-describing: the settings active during that session are always available, regardless of what the device is configured to later.

### Firmware Implementation Plan (`ble_telemetry.py`)

- Add `7f6d0003` to the existing GATT service with read + write-with-response permissions.
- On **read**: assemble 8-byte struct from `microcontroller.nvm[0:8]`. If any byte is 0xFF (uninitialised), substitute the field's default before returning.
- On **write**: validate `struct_version` matches firmware's expected version — reject silently if not. Validate each field is within allowed range — clamp out-of-range values. Write validated fields to `microcontroller.nvm[0:8]`. Apply fields that take immediate effect (see Feature 2 for `arm_side`).
- Reserve `microcontroller.nvm[0:8]` exclusively for this struct. Any future NVM use starts at index 8.

### Companion App Implementation Plan (`tremor_recorder.html`)

- On BLE connect, read `7f6d0003` immediately. Settings screen shows a loading state until read completes.
- Cache result in session-scoped JS object `deviceSettings`. All writes merge into this object.
- On session start (`startRecording()`): copy current `deviceSettings` into the new session record.
- Settings screen gains a "Device settings" section (separate from the existing app-local aggregate interval / stim-window settings which remain in localStorage):
  - **Arm side**: Left / Right / Not set (maps to 1 / 2 / 0)
  - **Phase override**: Auto / Force positive crossing / Force negative crossing (collapsible, labelled "research use only")
- Write → read-back → confirm / error as per protocol above.
- On BLE disconnect during a write in progress: show error, re-read on reconnect before enabling further writes.
- Session export JSON: include `deviceSettings` under each session.

### Documentation Plan

- Help screen and `docs/`: explain that "Device settings" are stored on the device, survive power cycles, and are separate from app-local session settings. Explain that every exported recording carries the device settings that were active during that session.

### Open Questions

- [ ] 300 ms read-back delay: verify empirically that `microcontroller.nvm` write completes within this window on the QT Py ESP32-S3.
- [ ] Write-with-response: confirm CircuitPython's `adafruit_ble` supports this on the peripheral side.
- [ ] Security: no write protection planned for now. Revisit if used in a clinical setting.

---

## Feature 2: Arm-Side Configuration

### Goal

The device must know which arm it is on (left or right) so that Feature 3 can select the correct stimulation phase. The arm side is set once in the companion app and stored persistently in device NVM. If it is not set, the device does not stimulate.

### User Story

> As a patient or carer, I configure which arm the device is on once in the companion app. The device remembers it across power cycles. If it is not set, the app tells me clearly and no stimulation happens until I configure it.

### Mechanism

1. Patient (or carer) connects the companion app.
2. Opens Settings → selects Left or Right arm.
3. App writes `arm_side` field to the device via `7f6d0003`.
4. Firmware writes to NVM.
5. On every subsequent power-on, device reads NVM and has arm side immediately. No calibration, no detection, no posture.

If `arm_side == 0` (not set): the app shows a clear, prominent message — "Arm side not configured. Go to Settings to set it before starting a session." The Start recording button is disabled until arm side is set.

### Firmware Implementation Plan (`tremor_detection.py` + `ble_telemetry.py`)

- `tremor_detection.py`: on startup, read `microcontroller.nvm[1]` into `arm_side`. Expose `arm_side` to the BLE module.
- `ble_telemetry.py`: when the settings characteristic receives a write with a new `arm_side` value, write to `microcontroller.nvm[1]` and update the RAM variable immediately (takes effect in the current session without restart).
- `arm_side = 0`: the device reaches LOCKED state but does not call `run_biphasic_burst()`. No stimulation occurs. This is not an error state — it simply means the device has not been configured yet.

### Companion App Implementation Plan

- On connect: read `7f6d0003`. If `arm_side == 0`: show a clear prominent message on the start screen "Arm side not set — configure in Settings before recording." Disable the "Start recording" button.
- Start recording is only enabled when `arm_side` is 1 or 2.
- Settings screen: arm-side selector as described in Feature 1.
- Session export: `deviceSettings.armSide` is in every session record (via Feature 1 session header).

### Documentation Plan

- Help screen: explain that arm side must be set once before first use. Explain what happens if it is not set (no stimulation, app shows message).
- Manual: add sensor placement rule — device must always be on the **dorsal (back) side** of the wrist, with the marked end pointing toward the hand. This is a hard constraint: wrong placement inverts the phase selection in Feature 3.

### Open Questions

- [ ] NVM byte index: `arm_side` is at `microcontroller.nvm[1]` (byte 1 of the settings struct, after `struct_version` at byte 0). Confirm all startup code reads byte 1, not byte 0.
- [ ] "Not set" UX: should the Settings screen open automatically if arm side is not set when first connecting? Consider an onboarding flow for first use.

---

## Feature 3: Phase-Correct Stimulation (Single Phase per Cycle)

### Goal

This is the main goal of the entire backlog. Once the arm side is known (Feature 2), the firmware derives the correct zero-crossing polarity (positive or negative) to use as the stimulation trigger and fires **once per tremor cycle** at that crossing only.

### User Story

> As a patient, I want the device to fire one stimulation pulse per tremor cycle — at the moment my arm is moving closest to my body — so that the therapy correctly interrupts the tremor feedback loop instead of reinforcing it.

### Acceptance Criteria

1. With arm side set and sensor correctly placed (dorsal, mark toward hand), stimulation fires exactly once per tremor cycle.
2. The firing zero-crossing corresponds to the arm moving toward the body.
3. Behaviour is mirrored correctly for left vs. right arm.
4. If arm side is not set (`arm_side == 0`): device locks on to tremor but does not stimulate. App shows "Arm side not set — no stimulation active."
5. The phase can be overridden manually from the app Settings (research/diagnostic use only).
6. Stimulation count in telemetry increments once per cycle (previously twice).

### Phase Selection Logic

The BNO055 gyroscope measures angular velocity in its own sensor frame. The firmware already identifies the dominant tremor axis as a 3D unit vector. The angular velocity projected onto this axis oscillates at the tremor frequency; zero-crossings mark the turning points of the tremor cycle.

The two zero-crossings per cycle are:
- **Positive-going** (velocity crosses zero from negative to positive): arm reverses direction one way.
- **Negative-going** (velocity crosses zero from positive to negative): arm reverses direction the other way.

Which one corresponds to "arm moving toward body" depends on:
1. **Arm side (left/right)**: mirrors the anatomical rotation axis.
2. **Sensor placement**: sensor on the dorsal side with mark toward the hand — this fixes the sign convention. This is a hard constraint documented in Feature 2.

> ⚠ **Posture constraint for phase computation:**  
> The gravity vector provides up/down orientation. "Toward the body" is a roughly horizontal direction. For the derivation to work reliably, the arm should be approximately horizontal (extended forward or to the side) at the moment the device locks in. The firmware computes `fire_polarity` once at the LOCKED transition using the gravity vector at that instant. If the arm is near-vertical at lock-in, the gravity projection onto the tremor plane is weak — treat this as a degenerate case and do not stimulate until re-lock with a better posture.

**Derivation (to be validated on hardware before coding):**
1. At LOCKED transition: read gravity vector `g` and dominant tremor axis unit vector `t` (both from BNO055 NDOF output).
2. Project `g` onto the plane perpendicular to `t`: `g_perp = g − (g·t)t`. This gives the "downward" direction as seen from the tremor axis.
3. The "toward body" rotational direction = cross product of `t` and `g_perp`, sign-corrected for arm side (negated for left arm).
4. Compare this direction to the sign of the angular velocity projection at lock-in to select `fire_polarity`.

### Firmware Implementation Plan (`tremor_detection.py`)

- On transition to `LOCKED` state:
  - If `arm_side == 0` (not set): set `fire_polarity = NONE`. Do not call `run_biphasic_burst()` at any zero-crossing.
  - If `arm_side` is known (1 or 2) and `fire_polarity_override == 0`: compute `fire_polarity` using the derivation above.
  - If `fire_polarity_override != 0`: use override value directly.
  - If gravity projection is too weak (degenerate posture): set `fire_polarity = NONE`, do not stimulate.
- In `LOCKED` and `HOLDOVER` states: only call `run_biphasic_burst()` at zero-crossings matching `fire_polarity`. Skip all other crossings.
- Re-compute `fire_polarity` at each re-lock. The arm may have moved.
- **Do not extend the telemetry packet.** `fire_polarity` and `arm_side` are available to the app via the settings characteristic and the session header.

### Companion App Implementation Plan

- Recording screen: show "Arm side" (from `deviceSettings` cached at connect time) as a small read-only status field. No telemetry bytes needed — this comes from the settings read.
- If `deviceSettings.armSide == 0` and a recording is started (should be blocked by Feature 2, but as defence): show a persistent red warning on the recording screen "Arm side not set — device is not stimulating."
- Settings screen "Phase override" (from Feature 1): Auto / Force positive / Force negative. Labelled "Research / diagnostic use only."
- Session export: `deviceSettings.firePolarityOverride` is already in the session header from Feature 1.
- Stimulation count metric: relabel from "Stimulation count" to "Stimulation bursts".

### Documentation Plan

- Help screen: brief explanation that the device selects the stimulation phase automatically from the sensor and arm-side configuration. No user action needed beyond setting arm side once.
- Help screen: "If arm side is not set, the device detects your tremor but does not deliver stimulation. Set arm side in Settings."
- Manual: technical note on the phase-selection mechanism.

### Dependencies

- Feature 3 cannot start until Feature 2 is complete and `arm_side` is reliably written to NVM and read by firmware.
- **The phase derivation math must be validated on paper and on the physical device before writing any firmware.** Document the exact BNO055 axis convention (X/Y/Z vs. anatomical forearm axes) first.

### Open Questions

- [ ] Work out and document the BNO055 coordinate frame. Which sensor axis is along the forearm, which is lateral, which is dorsal-normal. This is the foundation of the entire derivation — get it wrong and the phase is inverted.
- [ ] Define "toward body" precisely for the expected tremor type. Essential Tremor typically involves pronation/supination and flexion/extension of the wrist. Is the therapeutically relevant motion adduction or flexion? May need per-patient validation in early trials.
- [ ] Degenerate posture threshold: how small does `|g_perp|` need to be before we consider the posture degenerate? Suggested: if `|g_perp| < 1.0 m/s²` (arm within ~6° of vertical), do not stimulate and log the reason.
- [ ] Amplitude-comparison validation: after shipping, consider an optional diagnostic mode where the device alternates phases for N cycles each and the app reports the tremor amplitude change. This lets a clinician verify the chosen phase actually reduces tremor, or flip it if not.
- [ ] Stimulation count relabelling: confirm "bursts" vs. "count" does not break comparison of old vs. new session exports for any ongoing trials.
