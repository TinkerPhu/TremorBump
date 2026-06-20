# Safety Warning

This is an **experimental, uncertified device** that applies electrical
stimulation to the human body at up to **40 V DC** through skin-contact
electrodes. It has **no medical certification or regulatory approval** of any
kind (no FDA clearance, no CE mark).

## Known risks specific to this design

- **Electric shock and burns.** 40 V through skin-contact electrodes can cause
  skin burns, nerve damage, or cardiac arrhythmia — particularly if electrodes
  shift, gel dries out, or skin impedance is locally high.
- **No hardware kill switch.** Stimulation continues if the phone disconnects
  or the firmware hangs. A firmware crash mid-burst may leave the H-bridge
  outputting continuous DC rather than balanced biphasic pulses, which causes
  electrochemical burns.
- **No current limiting.** There is no hardware circuit to cap delivered
  current. Electrode placement, gel quality, and skin condition directly
  determine what reaches your tissue.

## Contraindications

Do not build or use this device if you have any of the following:

- Cardiac conditions or arrhythmia history
- A pacemaker, implanted defibrillator, or any other implanted electronic device
- Epilepsy
- Pregnancy
- Broken, irritated, or damaged skin at the intended electrode site

## Rules for use

- Use only on yourself. Do not use on another person without their explicit,
  informed consent and without them having read this document.
- Never place electrodes near the chest, neck, or head.
- Always have a second person present who can physically remove the electrodes
  or cut power in an emergency.
- Stop immediately if you experience unexpected sensations, pain, or muscle
  contractions outside the intended wrist area.
- Do not use while alone, while fatigued, or while impaired.
- Inspect electrodes and gel before every session. Do not use if gel has dried,
  if electrodes have shifted, or if the skin at the contact site is irritated.

## Liability

The author(s) of this project accept no liability whatsoever for injury,
damage, or any other harm resulting from building, modifying, or using this
design. **You build and use it entirely at your own risk.**
