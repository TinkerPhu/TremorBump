# SPDX-FileCopyrightText: 2026
# SPDX-License-Identifier: MIT

"""
CircuitPython 9.x tremor-synchronized stimulation  --  v7

Hardware:
- Adafruit QT Py ESP32-S3  (BLE required; ESP32-S2 has no Bluetooth)
- BNO055 on I2C  (NDOF fusion mode, default)
- H-bridge:  board.MOSI -> h_bridge_1,  board.MISO -> h_bridge_2
- Onboard NeoPixel for state / polarity indication

Detection concept:
- Sample gyro at SAMPLE_HZ.  Remove slowly adapting DC bias.
- Track dominant tremor axis with a 3-D direction EWMA (no cardinal snapping).
  If USE_WORLD_FRAME=True, rotate gyro into world frame via BNO055 quaternion
  before axis tracking so arm movement does not confuse the axis estimate.
- Detect hysteretic zero crossings; interpolate crossing time.
- Estimate tremor frequency from alternating crossing intervals.
- LOCKED: phase-correct stimulation schedule at every measured crossing.
  Dead-reckon between crossings with _advance_schedule.
- HOLDOVER: when signal is lost, continue stimulation at the last known
  frequency for HOLDOVER_TIMEOUT_S using the same scheduler.
- Fast re-lock: when signal returns from HOLDOVER, skip re-deriving the axis
  and require only RELOCKING_REQUIRED_CROSSES crossings.

BLE telemetry (v6 addition):
- Advertises as "TREMOR" using the custom service in ble_telemetry.py.
- Sends a 16-byte notify packet at BLE_NOTIFY_HZ (default 2 Hz).
- The ESP-IDF BLE stack runs as a FreeRTOS background task; the connection
  stays alive during blocking stimulation bursts (~30 ms).
- Connect from tremor_ble_recorder.html in Chrome / Edge.

This is experimental code. Validate on isolated test hardware only.
"""

import math
import time

import adafruit_bno055
import board
import busio
import digitalio
import neopixel
import supervisor


# -- HARDWARE PINS --------------------------------------------------------------

I2C_SCL          = board.SCL
I2C_SDA          = board.SDA
H_BRIDGE_1_PIN   = board.MOSI
H_BRIDGE_2_PIN   = board.MISO
NEOPIXEL_PIN     = board.NEOPIXEL
NEOPIXEL_COUNT   = 1
NEOPIXEL_BRIGHTNESS = 0.25


# -- TIMING & SAMPLE RATE -------------------------------------------------------

SAMPLE_HZ          = 75.0
SAMPLE_DT          = 1.0 / SAMPLE_HZ
MIN_TREMOR_HZ      = 2.0
MAX_TREMOR_HZ      = 8.0
MIN_HALF_PERIOD_S  = 0.5 / MAX_TREMOR_HZ   # 0.0625 s
MAX_HALF_PERIOD_S  = 0.5 / MIN_TREMOR_HZ   # 0.250  s


# -- STATE LABELS ---------------------------------------------------------------

UNLOCKED = "UNLOCKED"
LOCKING  = "LOCKING"
LOCKED   = "LOCKED"
HOLDOVER = "HOLDOVER"


# -- STIMULATION PARAMETERS -----------------------------------------------------

PEAK_POS = "(+)"
PEAK_NEG = "(-)"

PHASE_US                 = 250
INTERPHASE_GAP_US        = 1
INTERNAL_PULSE_HZ        = 200
STIM_DUTY_CYCLE          = 0.125
HOLDOVER_DUTY_SCALE      = 0.5
# 0.0 = stimulate at predicted peak; 0.5 = half period after peak
STIM_PHASE_OFFSET_CYCLES = 0.0
MIN_STIM_INTERVAL_S      = 0.050


# -- DETECTOR TUNING ------------------------------------------------------------

GYRO_BIAS_TAU_S      = 2.0    # gyro DC drift removal (4.0 by original design)

AXIS_LOCKING_TAU_S   = 0.35   # axis EWMA time constant during LOCKING (fast)
AXIS_LOCKED_TAU_S    = 2.0    # axis EWMA time constant during LOCKED  (slow)

AMP_ENV_TAU_S        = 0.30   # projected-signal envelope
THRESHOLD_FRACTION   = 0.28   # hysteresis band = amp_env * this
MIN_CROSS_THRESHOLD_DPS = 0.8
MIN_LOCK_ENV_DPS     = 2.0    # minimum envelope to consider signal valid

# Cold-start locking: require this many alternating crossings.
LOCKING_REQUIRED_ALTERNATING_CROSSES = 4
# Fast re-lock after HOLDOVER (axis already known): fewer crossings needed.
RELOCKING_REQUIRED_CROSSES           = 2
LOCKING_TIMEOUT_S     = 2.0   # abort LOCKING if no lock within this time
LOCKED_MISS_TIMEOUT_S = 1.2   # LOCKED -> HOLDOVER if no valid signal this long
# LOCKED -> HOLDOVER if no zero crossing for this long (catches wrong-axis freeze).
# Two full slow-tremor half-periods: tolerates one missed crossing.
LOCKED_NO_CROSS_TIMEOUT_S = 2.0 * MAX_HALF_PERIOD_S   # = 0.5 s

HOLDOVER_TIMEOUT_S   = 5.0    # HOLDOVER -> UNLOCKED if still no signal

FREQ_ALPHA_LOCKING   = 0.35   # frequency EMA blend during LOCKING
FREQ_ALPHA_LOCKED    = 0.18   # frequency EMA blend during LOCKED
FREQ_ALPHA_SCHED     = 0.08   # sched_hz EMA blend -- slower, for stable dead-reckoning

# If True, rotate sensor-frame gyro into world frame via BNO055 quaternion.
# Requires BNO055 NDOF fusion mode (the default). Falls back to sensor-frame
# automatically when bno.quaternion returns None (uncalibrated / wrong mode).
USE_WORLD_FRAME = True

# BLE telemetry notify rate. 2 Hz is enough for smooth live display and keeps
# BLE overhead well below 1% of loop time.
BLE_NOTIFY_HZ = 2.0

# flags byte bits in BLE packet:
#   bit 0  stim_enabled  state is LOCKED or HOLDOVER (stimulation may fire)
#   bit 1  polarity_ok   axis polarity has been established

ENABLE_FREQUENCY_TRACING = True   # 1-Hz state/frequency dump
ENABLE_LED_TRACING        = False    # print each LED_NEG ON event with interval
DEBUG_EVERY_S             = 1.0


# -- LED COLORS -----------------------------------------------------------------

LED_OFF           = (0,   0,   0)
LED_POS           = (2,   0,   0)
LED_NEG           = (0, 200,   0)
LED_LOCKING       = (8,   8,   0)
LED_UNLOCKED      = (0,   0,   8)
LED_HOLDOVER_STIM = (16, 16,  16)


# -- VECTOR & QUATERNION MATH  (pure functions, no heap allocation) -------------

def safe_print(*args):
    if supervisor.runtime.usb_connected:
        print(*args)


def v_add(a, b):    return (a[0]+b[0],  a[1]+b[1],  a[2]+b[2])
def v_sub(a, b):    return (a[0]-b[0],  a[1]-b[1],  a[2]-b[2])
def v_scale(a, s):  return (a[0]*s,     a[1]*s,     a[2]*s)
def v_dot(a, b):    return  a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def v_norm(a):      return  math.sqrt(v_dot(a, a))


def v_normalize(a, fallback=(1.0, 0.0, 0.0)):
    n = v_norm(a)
    if n <= 1e-6:
        return fallback
    return (a[0]/n, a[1]/n, a[2]/n)


def exp_alpha(dt, tau):
    """EMA blending factor for time step dt and time constant tau."""
    if tau <= 0.0:
        return 1.0
    return 1.0 - math.exp(-dt / tau)


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def q_conjugate(q):
    """Quaternion conjugate.  q = (w, x, y, z)."""
    return (q[0], -q[1], -q[2], -q[3])


def q_mul(p, q):
    """Hamilton product of two quaternions."""
    pw, px, py, pz = p
    qw, qx, qy, qz = q
    return (
        pw*qw - px*qx - py*qy - pz*qz,
        pw*qx + px*qw + py*qz - pz*qy,
        pw*qy - px*qz + py*qw + pz*qx,
        pw*qz + px*qy - py*qx + pz*qw,
    )


def q_rotate_vec(q, v):
    """Rotate vector v by unit quaternion q  (sandwich product q*v*q*)."""
    qv = (0.0, v[0], v[1], v[2])
    r  = q_mul(q_mul(q, qv), q_conjugate(q))
    return (r[1], r[2], r[3])


# -- HARDWARE LAYER -------------------------------------------------------------

_h1 = digitalio.DigitalInOut(H_BRIDGE_1_PIN)
_h1.direction = digitalio.Direction.OUTPUT
_h1.value = False

_h2 = digitalio.DigitalInOut(H_BRIDGE_2_PIN)
_h2.direction = digitalio.Direction.OUTPUT
_h2.value = False

pixels = neopixel.NeoPixel(NEOPIXEL_PIN, NEOPIXEL_COUNT,
                            brightness=NEOPIXEL_BRIGHTNESS, auto_write=True)
pixels[0] = LED_OFF


def bridge_idle():
    _h1.value = False
    _h2.value = False


def _bridge_positive():
    _h1.value = False
    _h2.value = True


def _bridge_negative():
    _h1.value = True
    _h2.value = False


def run_biphasic_burst(tremor_hz, polarity, holdover=False):
    """Deliver a symmetric biphasic burst.  Blocks for the burst duration.
    Returns number of pulses delivered."""
    if tremor_hz <= 0.0:
        return 0

    duty     = STIM_DUTY_CYCLE * (HOLDOVER_DUTY_SCALE if holdover else 1.0)
    burst_s  = duty / tremor_hz
    n_pulses = max(1, int(round(burst_s * INTERNAL_PULSE_HZ)))

    pixels[0] = (LED_HOLDOVER_STIM if holdover
                 else (LED_POS if polarity == PEAK_POS else LED_NEG))

    period_s = 1.0 / INTERNAL_PULSE_HZ
    pulse_s  = (PHASE_US * 2 + INTERPHASE_GAP_US) / 1_000_000.0
    idle_s   = max(0.0, period_s - pulse_s)

    for _ in range(n_pulses):
        _bridge_positive()
        time.sleep(PHASE_US / 1_000_000.0)
        bridge_idle()
        time.sleep(INTERPHASE_GAP_US / 1_000_000.0)
        _bridge_negative()
        time.sleep(PHASE_US / 1_000_000.0)
        bridge_idle()
        if idle_s > 0.0:
            time.sleep(idle_s)

    pixels[0] = LED_OFF
    return n_pulses


# -- TREMOR DETECTOR ------------------------------------------------------------

class TremorDetector:
    """
    3-D gyro tremor detector with axis-locked zero-crossing detection.

    Public read fields used by the main loop:
      state               - UNLOCKED / LOCKING / LOCKED / HOLDOVER
      tremor_hz           - live smoothed frequency estimate (responsive)
      sched_hz            - heavily filtered frequency for dead-reckoning scheduler
      stim_hz             - scheduling frequency (= tremor_hz in LOCKED,
                            frozen snapshot in HOLDOVER)
      amp_env             - axis-projected amplitude envelope (deg/s); used for
                            internal thresholds and crossing detection
      mag_env             - 3-D gyro magnitude envelope (deg/s); axis-independent,
                            more sensitive; use this for clinical amplitude reporting
      next_stim_t         - monotonic time of next stimulation (None = none scheduled)
      next_stim_polarity  - PEAK_POS or PEAK_NEG
      last_stim_polarity  - polarity of the most recently fired stim
      polarity_locked     - True once the tremor axis sign has been established
      came_from_holdover  - True while in the fast re-lock path

    Call update(gyro_dps, quat, now) at SAMPLE_HZ.
    After a stim fires, the main loop must set next_stim_t = None and call
    _advance_schedule(now) to arm the next event.
    """

    def __init__(self):
        # Fields that survive preserve_axis resets are initialised here so
        # they always exist regardless of which reset path runs first.
        self.bias            = (0.0, 0.0, 0.0)
        self.axis            = (1.0, 0.0, 0.0)
        self.axis_ref        = (1.0, 0.0, 0.0)
        self.polarity_locked = False
        self.tremor_hz       = 0.0
        self.sched_hz        = 0.0
        self._reset(preserve_axis=False)  # sets amp_env, mag_env, and all other fields

    # -- Public update ----------------------------------------------------------

    def update(self, gyro_vec, quat, now):
        """Process one gyro sample.
        Returns (cross_t, direction) on a valid crossing, else None."""
        if self.prev_t is None:
            self.prev_t = now
            return None

        dt = now - self.prev_t
        if dt <= 0.0 or dt > 0.1:
            dt = SAMPLE_DT

        # 1. Bias removal (always sensor frame so the bias estimate stays
        #    valid regardless of arm orientation changes).
        ba        = exp_alpha(dt, GYRO_BIAS_TAU_S)
        self.bias = v_add(v_scale(self.bias, 1.0 - ba), v_scale(gyro_vec, ba))
        motion    = v_sub(gyro_vec, self.bias)

        # 2. Optional world-frame rotation via BNO055 quaternion.
        if USE_WORLD_FRAME and quat is not None:
            motion = q_rotate_vec(quat, motion)

        # 3. Axis tracking.
        self._update_axis(motion, dt)

        # 4. Project onto current best axis and update envelope.
        ref      = self.axis_ref if self.polarity_locked else self.axis
        amp      = v_dot(motion, ref)
        self._update_envelope(amp, v_norm(motion), dt)

        # 5. All state transitions live here and nowhere else.
        self._update_state(now)

        # 6. HOLDOVER -- pure dead-reckoning, no crossing logic.
        if self.state == HOLDOVER:
            if self.next_stim_t is None:
                self._advance_schedule(now)
            self.prev_amp = amp
            self.prev_t   = now
            return None

        # 7. Zero-crossing detection (UNLOCKED / LOCKING / LOCKED).
        crossing = None
        if self.prev_amp is not None:
            crossing = self._detect_crossing(amp, now, dt)

        if crossing is not None:
            cross_t, direction = crossing
            self.last_crossing_t = now
            self._process_crossing(cross_t, direction)

        # 8. Dead-reckoning fallback if LOCKED and no stim is queued yet.
        if self.state == LOCKED and self.next_stim_t is None:
            self._advance_schedule(now)

        self.prev_amp = amp
        self.prev_t   = now
        return crossing

    # -- State machine ----------------------------------------------------------

    def _update_state(self, now):
        """All state transitions in one place.
        Each branch returns immediately so one call produces at most one hop."""

        if self.state == UNLOCKED:
            if self.amp_env >= MIN_LOCK_ENV_DPS:
                self.state              = LOCKING
                self.locking_started_t  = now
                self.last_signal_t      = now
                self.last_crossing_t    = now
                self.alternating_crosses = 0
                self.last_cross_t       = None
                self.last_cross_dir     = 0
                if not self.came_from_holdover:
                    # Cold start: reset axis polarity for a clean search.
                    self.polarity_locked = False
                self._required_crosses  = (RELOCKING_REQUIRED_CROSSES
                                           if self.came_from_holdover
                                           else LOCKING_REQUIRED_ALTERNATING_CROSSES)
            return

        if self.state == LOCKING:
            if self.amp_env >= MIN_LOCK_ENV_DPS:
                self.last_signal_t = now
            timed_out   = now - self.locking_started_t > LOCKING_TIMEOUT_S
            lost_signal = now - self.last_signal_t     > LOCKED_MISS_TIMEOUT_S
            if timed_out or lost_signal:
                self._reset(preserve_axis=False)
            return

        if self.state == LOCKED:
            if self.amp_env >= MIN_LOCK_ENV_DPS:
                self.last_signal_t = now
            signal_gap = now - self.last_signal_t   > LOCKED_MISS_TIMEOUT_S
            cross_gap  = (self.last_crossing_t is not None and
                          now - self.last_crossing_t > LOCKED_NO_CROSS_TIMEOUT_S)
            if signal_gap or cross_gap:
                self._start_holdover(now)
            return

        if self.state == HOLDOVER:
            if now - self.holdover_started_t > HOLDOVER_TIMEOUT_S:
                self._reset(preserve_axis=False)
                return
            if self.amp_env >= MIN_LOCK_ENV_DPS:
                # Signal returned: fast re-lock, preserving axis geometry.
                self._reset(preserve_axis=True)
            return

    # -- Signal processing ------------------------------------------------------

    def _update_axis(self, motion, dt):
        """Unified EWMA axis tracker used in both LOCKING and LOCKED phases.

        LOCKING: fast time constant, anti-flip vs rolling self.axis.
        LOCKED:  slow time constant, anti-flip vs FROZEN self.axis_ref.
        The two cases share identical math; only tau and the reference differ."""
        if v_norm(motion) < MIN_CROSS_THRESHOLD_DPS:
            return
        candidate = v_normalize(motion, self.axis)
        if self.polarity_locked:
            if v_dot(candidate, self.axis_ref) < 0.0:
                candidate = v_scale(candidate, -1.0)
            a = exp_alpha(dt, AXIS_LOCKED_TAU_S)
        else:
            if v_dot(candidate, self.axis) < 0.0:
                candidate = v_scale(candidate, -1.0)
            a = exp_alpha(dt, AXIS_LOCKING_TAU_S)
        mixed     = v_add(v_scale(self.axis, 1.0 - a), v_scale(candidate, a))
        self.axis = v_normalize(mixed, self.axis)

    def _update_envelope(self, amp, mag, dt):
        a            = exp_alpha(dt, AMP_ENV_TAU_S)
        self.amp_env = self.amp_env * (1.0 - a) + abs(amp) * a
        self.mag_env = self.mag_env * (1.0 - a) + mag * a

    def _compute_threshold(self):
        return max(self.amp_env * THRESHOLD_FRACTION, MIN_CROSS_THRESHOLD_DPS)

    def _detect_crossing(self, amp, now, dt):
        """Hysteresis arming + zero-crossing detection + linear interpolation.
        Returns (cross_t, direction) or None.  Pure detection, no side effects."""
        threshold = self._compute_threshold()

        if amp > threshold:
            self.armed_neg = True
        elif amp < -threshold:
            self.armed_pos = True

        prev      = self.prev_amp
        direction = 0

        if prev < 0.0 and amp >= 0.0 and self.armed_pos:
            direction      = 1
            self.armed_pos = False
        elif prev > 0.0 and amp <= 0.0 and self.armed_neg:
            direction      = -1
            self.armed_neg = False

        if direction == 0:
            return None

        denom   = amp - prev
        frac    = clamp(-prev / denom, 0.0, 1.0) if abs(denom) > 1e-6 else 1.0
        cross_t = self.prev_t + frac * dt
        return (cross_t, direction)

    def _update_frequency(self, half_period_s):
        """EMA update of tremor_hz from a measured half-period."""
        hz = 1.0 / (half_period_s * 2.0)
        if hz < MIN_TREMOR_HZ or hz > MAX_TREMOR_HZ:
            return
        if self.state == LOCKED and self.amp_env < MIN_LOCK_ENV_DPS:
            return
        if self.tremor_hz <= 0.0:
            self.tremor_hz = hz
        else:
            alpha          = FREQ_ALPHA_LOCKED if self.state == LOCKED else FREQ_ALPHA_LOCKING
            self.tremor_hz = self.tremor_hz * (1.0 - alpha) + hz * alpha
        # Keep stim_hz / sched_hz current during LOCKED/LOCKING.
        # _start_holdover freezes them by not updating in HOLDOVER state.
        if self.state != HOLDOVER:
            self.stim_hz = self.tremor_hz
            if self.sched_hz <= 0.0:
                self.sched_hz = self.tremor_hz
            else:
                self.sched_hz = (self.sched_hz * (1.0 - FREQ_ALPHA_SCHED)
                                 + self.tremor_hz * FREQ_ALPHA_SCHED)

    # -- Crossing processing ----------------------------------------------------

    def _process_crossing(self, cross_t, direction):
        """Half-period bookkeeping, frequency update, lock transition, and
        schedule phase-correction -- all triggered by one detected crossing."""
        if self.last_cross_t is not None:
            half_period_s = cross_t - self.last_cross_t
            if MIN_HALF_PERIOD_S <= half_period_s <= MAX_HALF_PERIOD_S:
                if direction != self.last_cross_dir:
                    self.alternating_crosses += 1
                    self._update_frequency(half_period_s)
                else:
                    # Two consecutive same-direction crossings: missed opposite.
                    self.alternating_crosses = 0
            else:
                self.alternating_crosses = 0

        prev_cross_dir      = self.last_cross_dir
        self.last_cross_t   = cross_t
        self.last_cross_dir = direction

        # LOCKING -> LOCKED: triggered by crossing count reaching the threshold.
        if self.state == LOCKING:
            if self.alternating_crosses >= self._required_crosses:
                self.state              = LOCKED
                self.locking_started_t  = None
                self.came_from_holdover = False
                if not self.polarity_locked:
                    self._lock_axis_polarity()

        # Phase-correct only on valid alternating crossings -- same guard as
        # frequency update -- so noise same-direction crossings do not shift the
        # stim schedule away from the actual tremor peak.
        if self.state == LOCKED and direction != prev_cross_dir:
            self._schedule_from_crossing(cross_t, direction)

    # -- Axis polarity ----------------------------------------------------------

    def _lock_axis_polarity(self):
        """Freeze the current axis as the polarity reference.
        This is the ONLY place axis_ref is ever written after __init__."""
        self.axis        = v_normalize(self.axis)
        self.axis_ref    = self.axis
        self.polarity_locked = True

    # -- Scheduler --------------------------------------------------------------

    def _schedule_from_crossing(self, cross_t, direction):
        """Phase-correct the stim schedule using a measured zero crossing.
        Overrides any existing next_stim_t with a phase-accurate value."""
        if self.tremor_hz <= 0.0:
            return
        period_s = 1.0 / self.tremor_hz
        polarity = PEAK_POS if direction > 0 else PEAK_NEG
        self.next_stim_t        = (cross_t
                                   + period_s * 0.25
                                   + period_s * STIM_PHASE_OFFSET_CYCLES)
        self.next_stim_polarity = polarity

    def _advance_schedule(self, now):
        """Dead-reckoning: schedule next stim one half-period from now.
        Only acts when next_stim_t is None.  Works for LOCKED and HOLDOVER.
        Uses sched_hz (heavily filtered) so jitter in tremor_hz does not shift
        the dead-reckoning window.  last_stim_polarity is written here so that
        consecutive dead-reckoning calls self-alternate without needing a crossing."""
        if self.next_stim_t is not None:
            return
        hz = self.sched_hz if self.sched_hz > 0.0 else self.stim_hz
        if hz <= 0.0:
            return
        period_s = 1.0 / hz
        polarity = PEAK_NEG if self.last_stim_polarity == PEAK_POS else PEAK_POS
        self.next_stim_t        = (now
                                   + period_s * 0.5
                                   + period_s * STIM_PHASE_OFFSET_CYCLES)
        self.next_stim_polarity = polarity
        self.last_stim_polarity = polarity

    # -- Holdover entry ---------------------------------------------------------

    def _start_holdover(self, now):
        """Snapshot current frequency and switch to pure dead-reckoning."""
        if self.tremor_hz <= 0.0:
            self._reset(preserve_axis=False)
            return
        self.stim_hz            = self.tremor_hz   # snapshot, not a history median
        self.state              = HOLDOVER
        self.holdover_started_t = now
        self.next_stim_t        = None
        self._advance_schedule(now)

    # -- Reset ------------------------------------------------------------------

    def _reset(self, preserve_axis):
        """Reset to UNLOCKED.

        preserve_axis=False  full cold-start: clear all state including axis.
        preserve_axis=True   soft reset: keep axis, axis_ref, polarity_locked,
                             and tremor_hz so the subsequent LOCKING phase is fast.
        """
        self.state              = UNLOCKED
        self.locking_started_t  = None
        self.last_signal_t      = time.monotonic()
        self.last_crossing_t    = None
        self.alternating_crosses = 0
        self.last_cross_t       = None
        self.last_cross_dir     = 0
        self.stim_hz            = 0.0
        self.next_stim_t        = None
        self.next_stim_polarity = PEAK_POS
        self.last_stim_polarity = PEAK_POS
        self.holdover_started_t = None
        self.amp_env            = 0.0
        self.mag_env            = 0.0
        self.armed_pos          = False
        self.armed_neg          = False
        self.prev_amp           = None
        self.prev_t             = None

        if preserve_axis:
            self.came_from_holdover = True
            self._required_crosses  = RELOCKING_REQUIRED_CROSSES
            # tremor_hz, sched_hz, axis, axis_ref, polarity_locked preserved implicitly
        else:
            self.bias               = (0.0, 0.0, 0.0)
            self.axis               = (1.0, 0.0, 0.0)
            self.axis_ref           = (1.0, 0.0, 0.0)
            self.polarity_locked    = False
            self.tremor_hz          = 0.0
            self.sched_hz           = 0.0
            self.came_from_holdover = False
            self._required_crosses  = LOCKING_REQUIRED_ALTERNATING_CROSSES


# -- SENSOR & BLE SETUP ---------------------------------------------------------

bridge_idle()

i2c = busio.I2C(I2C_SCL, I2C_SDA, frequency=400000)
bno = adafruit_bno055.BNO055_I2C(i2c)

_RAD_TO_DPS = 180.0 / math.pi

# Quaternion changes at arm-rotation speed, not tremor speed; 15 Hz is ample.
# Reading it every loop at 75 Hz doubles the I2C cost for no benefit.
_QUAT_EVERY     = 5          # read quaternion once every N gyro samples (~15 Hz)
_quat_countdown = 0
_cached_quat    = None


def read_sensor():
    """Return (gyro_dps, quat).  Quaternion is re-read every _QUAT_EVERY calls
    and cached in between; gyro is read on every call.
    Either field may be None on read failure or before first quat read."""
    global _quat_countdown, _cached_quat
    g = bno.gyro
    if g is None:
        return None, None
    gyro = (g[0] * _RAD_TO_DPS, g[1] * _RAD_TO_DPS, g[2] * _RAD_TO_DPS)
    if USE_WORLD_FRAME:
        _quat_countdown -= 1
        if _quat_countdown <= 0:
            _cached_quat    = bno.quaternion
            _quat_countdown = _QUAT_EVERY
    return gyro, _cached_quat


from ble_telemetry import BLETremorTelemetry
telemetry = BLETremorTelemetry(name="TREMOR", notify_hz=BLE_NOTIFY_HZ)
telemetry.debug_print_identity()


# -- MAIN LOOP ------------------------------------------------------------------

detector      = TremorDetector()
next_sample_t = time.monotonic()
last_debug_t  = next_sample_t
last_rate_t   = next_sample_t
last_stim_t   = 0.0
last_led_neg_t = None   # for LED_NEG interval tracing
sample_count  = 0
actual_hz     = 0.0
late_samples  = 0
stim_count    = 0

pixels[0] = LED_UNLOCKED
safe_print("simple_detection_v6 ready")


def update_idle_led():
    if detector.state == UNLOCKED:
        pixels[0] = LED_UNLOCKED
    elif detector.state == LOCKING:
        pixels[0] = LED_LOCKING
    else:
        pixels[0] = LED_OFF   # burst flash handles LOCKED / HOLDOVER indication


while True:
    now = time.monotonic()

    # Fixed-rate timing gate.
    if now < next_sample_t:
        gap = next_sample_t - now
        time.sleep(min(gap, 0.002))
        continue

    sample_t = now
    if sample_t - next_sample_t > SAMPLE_DT:
        late_samples += 1
    next_sample_t = sample_t + SAMPLE_DT

    gyro, quat = read_sensor()

    if gyro is not None:
        sample_count += 1

    if now - last_rate_t >= 1.0:
        actual_hz    = sample_count / (now - last_rate_t)
        sample_count = 0
        last_rate_t  = now

    if gyro is None:
        bridge_idle()
        telemetry.maintain()
        continue

    detector.update(gyro, quat, sample_t)

    # Fire scheduled stimulation -- unified path for LOCKED and HOLDOVER.
    if (detector.next_stim_t is not None
            and sample_t >= detector.next_stim_t
            and sample_t - last_stim_t >= MIN_STIM_INTERVAL_S
            and detector.state in (LOCKED, HOLDOVER)):

        run_biphasic_burst(
            detector.stim_hz,
            detector.next_stim_polarity,
            holdover=(detector.state == HOLDOVER),
        )
        if ENABLE_LED_TRACING and not (detector.state == HOLDOVER) and detector.next_stim_polarity == PEAK_NEG:
            _interval = round(sample_t - last_led_neg_t, 4) if last_led_neg_t is not None else None
            if _interval is not None and _interval < 0.1:
                safe_print("LED_NEG_SHORT", "interval_s", _interval, "hz", round(detector.stim_hz, 2), "schz", round(detector.sched_hz, 2))
            safe_print("LED_NEG", "hz", round(detector.stim_hz, 2), "schz", round(detector.sched_hz, 2), "mag", round(detector.mag_env, 1), "interval_s", _interval)
            last_led_neg_t = sample_t
        stim_count  += 1
        last_stim_t  = time.monotonic()
        detector.last_stim_polarity = detector.next_stim_polarity
        detector.next_stim_t = None
        detector._advance_schedule(time.monotonic())

    update_idle_led()

    _ble_tremor_hz = detector.tremor_hz if detector.state != UNLOCKED else 0.0
    telemetry.update(
        now=sample_t,
        state=detector.state,
        sched_hz=detector.sched_hz,
        tremor_hz=_ble_tremor_hz,
        mag_env=detector.mag_env,
        stim_count=stim_count,
    )

    if ENABLE_FREQUENCY_TRACING and sample_t - last_debug_t >= DEBUG_EVERY_S:
        last_debug_t = sample_t
        _ax = detector.axis_ref if detector.polarity_locked else detector.axis
        _cal = ""
        if USE_WORLD_FRAME:
            cal = bno.calibration_status
            _cal = " cal" + str(cal) if cal is not None else " cal?"
        safe_print(
            detector.state,
            "hz",     round(detector.tremor_hz, 2),
            "shz",    round(detector.stim_hz,   2),
            "schz",   round(detector.sched_hz,  2),
            "mag",    round(detector.mag_env,    1),
            "env",    round(detector.amp_env,    1),
            "axis",   tuple(round(x, 2) for x in _ax),
            "pol",    detector.polarity_locked,
            "hov",    detector.came_from_holdover,
            "stim",   stim_count,
            "ble",    telemetry.connected(),
            "hz_act", round(actual_hz, 1),
            "slow",   late_samples,
            _cal,
        )
