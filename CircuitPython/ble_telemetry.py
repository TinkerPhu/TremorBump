# SPDX-FileCopyrightText: 2026
# SPDX-License-Identifier: MIT

"""
ble_telemetry.py

BLE telemetry helper for the tremor-synchronized stimulation prototype.

This version uses the normal CircuitPython BLE service-advertising pattern:

    advertisement = ProvideServicesAdvertisement(service)
    scan_response = Advertisement()
    scan_response.complete_name = "TREMOR"
    ble.start_advertising(advertisement, scan_response, interval=0.1)

Reason:
- A custom 128-bit service UUID is needed so Web Bluetooth can discover the
  telemetry service.
- The visible device name may not fit in the main advertisement.
- Therefore the name is placed in the scan response.

Packet format, little-endian, exactly 13 bytes:

    uint32  device_t_ms      raw milliseconds (wraps ~49 days)
    uint8   state_code       0=UNLOCKED 1=LOCKING 2=LOCKED 3=HOLDOVER 255=unknown
    uint16  sched_hz_x100    scheduling frequency × 100  (0.01 Hz resolution)
    uint16  tremor_hz_x100   measured frequency × 100    (0.01 Hz resolution)
    uint16  mag_env_x10      3-D magnitude envelope × 10 (0.1 deg/s resolution)
    uint16  stim_count       cumulative stimulation count (wraps at 65535)
"""

import struct

from adafruit_ble import BLERadio
from adafruit_ble.advertising import Advertisement
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.attributes import Attribute
from adafruit_ble.characteristics import Characteristic
from adafruit_ble.services import Service
from adafruit_ble.uuid import VendorUUID


TREMOR_SERVICE_UUID = VendorUUID("7f6d0001-6f7a-4f4e-9a8b-3b7f4b000001")
TELEMETRY_CHAR_UUID = VendorUUID("7f6d0002-6f7a-4f4e-9a8b-3b7f4b000001")

STATE_UNKNOWN = 255
STATE_CODES = {
    "UNLOCKED": 0,
    "LOCKING":  1,
    "LOCKED":   2,
    "HOLDOVER": 3,
}

_PACKET_FORMAT = "<LBHHHH"
_PACKET_LEN = 13
_ZERO_PACKET = bytes(_PACKET_LEN)


class TremorTelemetryService(Service):
    uuid = TREMOR_SERVICE_UUID

    telemetry = Characteristic(
        uuid=TELEMETRY_CHAR_UUID,
        properties=Characteristic.READ | Characteristic.NOTIFY,
        read_perm=Attribute.OPEN,
        write_perm=Attribute.NO_ACCESS,
        max_length=_PACKET_LEN,
        fixed_length=True,
        initial_value=_ZERO_PACKET,
    )


class BLETremorTelemetry:
    def __init__(self, name="TREMOR", notify_hz=2.0, debug=True):
        self.name = name
        self.notify_hz = notify_hz
        self.notify_interval_s = 1.0 / notify_hz if notify_hz > 0.0 else 1.0
        self.debug = debug

        self.ble = BLERadio()
        try:
            self.ble.name = name
        except Exception:
            pass

        self.service = TremorTelemetryService()

        # Main advertisement: includes the custom service UUID.
        self.advertisement = ProvideServicesAdvertisement(self.service)

        # Scan response: includes the visible device name.
        self.scan_response = Advertisement()
        self.scan_response.complete_name = name
        self.scan_response.short_name = name

        self._last_notify_t = -9999.0
        self._packet = bytearray(_PACKET_LEN)
        self._advertising = False
        self._last_connected = False

    def address_string(self):
        try:
            address = self.ble.address_bytes
        except Exception:
            return "unknown"

        parts = []
        for b in address:
            parts.append("%02X" % b)
        return ":".join(parts)

    def debug_print_identity(self):
        print("BLE name", self.name)
        print("BLE address", self.address_string())
        print("BLE service", "7f6d0001-6f7a-4f4e-9a8b-3b7f4b000001")
        print("BLE telemetry", "7f6d0002-6f7a-4f4e-9a8b-3b7f4b000001")

    def start_advertising(self):
        if self.ble.connected:
            return
        if self._advertising:
            return
        try:
            self.ble.start_advertising(
                self.advertisement,
                self.scan_response,
                interval=0.1,
            )
            self._advertising = True
            if self.debug:
                print("BLE advertising", self.name, self.address_string())
        except Exception as exc:
            self._advertising = False
            if self.debug:
                print("BLE advertising failed", repr(exc))

    def stop_advertising(self):
        if not self._advertising:
            return
        try:
            self.ble.stop_advertising()
        except Exception:
            pass
        self._advertising = False

    def maintain(self):
        connected = self.ble.connected

        if connected != self._last_connected:
            self._last_connected = connected
            if self.debug:
                print("BLE connected", connected)

        if connected:
            self._advertising = False
            return

        self.start_advertising()

    def connected(self):
        return self.ble.connected

    def update(
        self,
        now,
        state,
        sched_hz,
        tremor_hz,
        mag_env,
        stim_count,
        allow_send=True,
    ):
        self.maintain()

        if not allow_send:
            return False
        if not self.ble.connected:
            return False
        if now - self._last_notify_t < self.notify_interval_s:
            return False

        struct.pack_into(
            _PACKET_FORMAT,
            self._packet,
            0,
            self._clamp_u32(int(now * 1000.0)),
            self._clamp_u8(STATE_CODES.get(state, STATE_UNKNOWN)),
            self._clamp_u16(int(sched_hz * 100.0 + 0.5)),
            self._clamp_u16(int(tremor_hz * 100.0 + 0.5)),
            self._clamp_u16(int(mag_env * 10.0 + 0.5)),
            self._clamp_u16(stim_count),
        )

        try:
            self.service.telemetry = self._packet
            self._last_notify_t = now
            return True
        except Exception as exc:
            if self.debug:
                print("BLE notify failed", repr(exc))
            return False

    def _clamp_u8(self, value):
        if value < 0:
            return 0
        if value > 255:
            return 255
        return int(value)

    def _clamp_u16(self, value):
        if value < 0:
            return 0
        if value > 65535:
            return 65535
        return int(value)

    def _clamp_u32(self, value):
        if value < 0:
            return 0
        if value > 4294967295:
            return 4294967295
        return int(value)
