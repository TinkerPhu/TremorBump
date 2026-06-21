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

**Possible solutions:**
1. Add a user-selectable "Left arm / Right arm" setting and a "Sensor orientation" calibration step in the firmware/app, then derive the correct phase mathematically.
2. Add a short automatic calibration routine: fire at π/2 for N cycles, measure tremor amplitude change, then try 3π/2 for N cycles, and lock on whichever phase reduces amplitude.
3. Expose the firing phase as a configurable parameter in the companion app so the therapist or user can tune it empirically.

**References:**  
See `docs/SES_Clinical_Reference.md` for the neurophysiology of phase-locked stimulation and the importance of stimulation timing relative to the tremor cycle.
