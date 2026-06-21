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

**References:**  
See `docs/SES_Clinical_Reference.md` for the neurophysiology of phase-locked stimulation and the importance of stimulation timing relative to the tremor cycle.
