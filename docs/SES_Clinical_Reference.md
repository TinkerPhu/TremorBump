# SES for Hand Tremors in Senior Patients — Clinical Summary

Sensory Electrical Stimulation (SES) is a non-invasive neuromodulatory intervention that delivers electrical current at intensities below the motor threshold (MT) to engage sensory feedback loops without inducing overt muscle contractions. This project applies SES to **Essential Tremor (ET)** — the most prevalent movement disorder in seniors, producing a rhythmic action/postural hand tremor typically in the **5–8 Hz** range (full pathological range: 4–12 Hz).

> For a plain-language introduction to SES, see [`SES_Overview.md`](SES_Overview.md).

> Much of the published clinical SES literature focuses on Parkinson's disease (PD) tremor. The TremorBump device is mechanistically applicable to PD as well, but ET is the scope of this project. The clinical data cited below is drawn from PD and mixed-tremor studies where ET-specific data is limited; the neurophysiological mechanism (CTC circuit modulation) is shared between both conditions.

SES is distinguished from related modalities by its neurophysiological targets:

| Modality | Intensity vs. Motor Threshold | Primary Mechanism | Typical Frequency |
|---|---|---|---|
| **SES** | Below (sub-motor) | Central sensorimotor integration via proprioceptive afferents | 50–100 Hz |
| **FES** | Above | Induced muscle contraction | 20–40 Hz |
| **TENS** | Below | Inhibition via cutaneous afferents | 100–250 Hz |

---

## Technical Mechanisms and Neurophysiological Pathways

### Selective Fiber Activation

SES targets **Type Ia and Type Ib proprioceptive sensory fibers**. These fibers sit anatomically deeper than cutaneous afferents, requiring lower excitation levels to achieve central suppression:

- **Type Ia** — promotes reciprocal inhibition, enhancing agonist muscle control while reducing antagonistic co-activation.
- **Type Ib** — modulates the spinal stretch reflex through Ib inhibition.

### Central Circuit Modulation — the "Dimmer-Switch" Hypothesis

ET tremor is driven primarily by the **Cerebello-Thalamo-Cortical (CTC) circuit**, which governs tremor amplitude. SES provides artificial sensory feedback that interferes with the thalamic and cerebellar receptive fields within this circuit, "dimming" the pathological oscillations that produce the involuntary hand movement.

### Electrode Placement — Motor Points for Hand Tremor Suppression

| Muscle | Landmark |
|---|---|
| Flexor Carpi Radialis (FCR) | 4 fingerbreadths distal to the bicep tendon |
| Extensor Carpi Radialis (ECR) | 2 fingerbreadths distal to the lateral epicondyle |
| Flexor Carpi Ulnaris (FCU) | Junction of the middle and upper thirds of the forearm, volar to the ulna |

---

## Therapeutic Parameters and Clinical Protocol

### Stimulation Parameters

| Parameter | Value |
|---|---|
| Waveform | Biphasic square wave (charge-balanced; prevents tissue damage) |
| Trigger phase | Locked to ±amplitude peaks of the tremor cycle (½π and 1½π) |
| Duty cycle | 12.5% of the tremor period per burst |
| Carrier frequency | 100 Hz |
| Pulse width | 250 µs (Abass et al., 2025) or 300 µs (Heo et al.) |
| Intensity adjustment | 0.2 mA incremental steps, individualised to stay below motor threshold |

### Administration Schedule

| Parameter | Value |
|---|---|
| Session duration | 20–40 minutes |
| Weekly frequency | 3 sessions per week |
| Total treatment duration | 4 weeks (minimum 12 sessions) |

Cumulative treatment over a 4-week protocol facilitates circuit stabilisation. While acute relief is transient, tremor reduction typically persists for **1+ hour post-stimulation** following consistent administration.

---

## Patient Experience and Sensation Benchmarks

- **Target sensation:** a **strong but comfortable tingling or tickling** in the hand or fingers. This confirms the sensory threshold has been reached without crossing into motor territory.
- **Motor threshold signs:** visible muscle twitches or an electric shock sensation — intensity must be reduced immediately if either occurs.

> **Important:** SES must remain strictly below the motor threshold. Stimulation reaching motor levels can paradoxically worsen tremors by increasing patient anxiety and inducing muscle fatigue.

---

## Clinical Efficacy

The figures below are drawn from studies on mixed tremor and PD populations, as ET-specific SES trials remain limited. The CTC mechanism targeted here is shared with ET.

| Population / Scenario | Result |
|---|---|
| General SES (mixed tremor populations) | 35–48% average tremor power reduction |
| Phase-locked to ±peaks (½π and 1½π), severe tremors | 60–65% reduction in tremor power |
| SES combined with physical therapy, suitable responders (Abass et al., 2025) | Up to 83% average magnitude decrease |
| Study cohort Group A | Highly significant reduction in tremor frequency (t = 10.114, P < 0.001) |

### Functional Improvements

- **Fahn-Tolosa-Marin (FTM) scores:** highly significant reductions (P < 0.001) in tremor severity following the 12-session protocol.
- **FTM writing scores:** marked improvement, indicating restored fine motor control for daily tasks.

---

## References

- Meng, L., Jin, M., Zhu, X., & Ming, D. (2022). *Peripherical Electrical Stimulation for Parkinsonian Tremor: A Systematic Review.* https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8859162/
- Abass, M. Y., Badawy, M. S., Ahmed, G. M., Shendy, W., El-Jaafary, S. I., & Morsi, A. A. (2025). *Effect of Sensory Electrical Stimulation on Resting Tremors in Patients with Parkinson's Disease.* https://theaspd.com/index.php/ijes/article/download/7374/5335/15167
- Alam, M. (OpenMedTech Lab). *OpenVstim: Open Source Transcutaneous Voltage Stimulator.* https://github.com/MonzurulAlam/OpenVstim
