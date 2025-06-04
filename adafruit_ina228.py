# SPDX-FileCopyrightText: Copyright (c) 2025 Liz Clark for Adafruit Industries
#
# SPDX-License-Identifier: MIT
"""
`adafruit_ina228`
================================================================================

CircuitPython driver for the INA228 I2C 85V, 20-bit High or Low Side Power Monitor


* Author(s): Liz Clark

Implementation Notes
--------------------

**Hardware:**

* `Adafruit INA228 High Side Current and Power Monitor <https://www.adafruit.com/product/5832>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards: https://circuitpython.org/downloads

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
* Adafruit's Register library: https://github.com/adafruit/Adafruit_CircuitPython_Register
"""

import time

from adafruit_bus_device.i2c_device import I2CDevice
from adafruit_register.i2c_bit import RWBit
from adafruit_register.i2c_bits import RWBits
from adafruit_register.i2c_struct import UnaryStruct
from micropython import const

try:
    import typing

    from busio import I2C
except ImportError:
    pass

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_INA228.git"

# Register addresses
_CONFIG = const(0x00)  # Configuration Register
_ADC_CONFIG = const(0x01)  # ADC Configuration Register
_SHUNT_CAL = const(0x02)  # Shunt Calibration Register
_SHUNT_TEMPCO = const(0x03)  # Shunt Temperature Coefficient Register
_VSHUNT = const(0x04)  # Shunt Voltage Measurement
_VBUS = const(0x05)  # Bus Voltage Measurement
_DIETEMP = const(0x06)  # Temperature Measurement
_CURRENT = const(0x07)  # Current Result
_POWER = const(0x08)  # Power Result
_ENERGY = const(0x09)  # Energy Result
_CHARGE = const(0x0A)  # Charge Result
_DIAG_ALRT = const(0x0B)  # Diagnostic Flags and Alert
_SOVL = const(0x0C)  # Shunt Overvoltage Threshold
_SUVL = const(0x0D)  # Shunt Undervoltage Threshold
_BOVL = const(0x0E)  # Bus Overvoltage Threshold
_BUVL = const(0x0F)  # Bus Undervoltage Threshold
_TEMP_LIMIT = const(0x10)  # Temperature Over-Limit Threshold
_PWR_LIMIT = const(0x11)  # Power Over-Limit Threshold
_MFG_ID = const(0x3E)  # Manufacturer ID
_DEVICE_ID = const(0x3F)  # Device ID


class Mode:
    """Constants for operating modes"""

    SHUTDOWN = 0x00
    TRIGGERED_BUS = 0x01
    TRIGGERED_SHUNT = 0x02
    TRIGGERED_BUS_SHUNT = 0x03
    TRIGGERED_TEMP = 0x04
    TRIGGERED_TEMP_BUS = 0x05
    TRIGGERED_TEMP_SHUNT = 0x06
    TRIGGERED_ALL = 0x07
    SHUTDOWN2 = 0x08
    CONTINUOUS_BUS = 0x09
    CONTINUOUS_SHUNT = 0x0A
    CONTINUOUS_BUS_SHUNT = 0x0B
    CONTINUOUS_TEMP = 0x0C
    CONTINUOUS_TEMP_BUS = 0x0D
    CONTINUOUS_TEMP_SHUNT = 0x0E
    CONTINUOUS_ALL = 0x0F


class AlertType:
    """Constants for alert type settings"""

    NONE = 0x00
    CONVERSION_READY = 0x01
    OVERPOWER = 0x02
    UNDERVOLTAGE = 0x04
    OVERVOLTAGE = 0x08
    UNDERCURRENT = 0x10
    OVERCURRENT = 0x20
    _VALID_VALUES = [
        NONE,
        CONVERSION_READY,
        OVERPOWER,
        UNDERVOLTAGE,
        OVERVOLTAGE,
        UNDERCURRENT,
        OVERCURRENT,
    ]
    _MAX_COMBINED = 0x3F


class INA228:  # noqa: PLR0904
    """Driver for the INA228 power and current sensor"""

    _config = UnaryStruct(_CONFIG, ">H")
    _adc_config = UnaryStruct(_ADC_CONFIG, ">H")
    _shunt_cal = UnaryStruct(_SHUNT_CAL, ">H")
    _diag_alrt = UnaryStruct(_DIAG_ALRT, ">H")
    _adc_range = RWBit(_CONFIG, 4, register_width=2)
    _alert_type = RWBits(6, _DIAG_ALRT, 8, register_width=2)
    _alert_polarity_bit = RWBit(_DIAG_ALRT, 12, register_width=2)
    _alert_latch_bit = RWBit(_DIAG_ALRT, 15, register_width=2)
    _reset_bit = RWBit(_CONFIG, 15, register_width=2)
    _reset_accumulators_bit = RWBit(_CONFIG, 14, register_width=2)
    """Operating mode"""
    mode = RWBits(4, _ADC_CONFIG, 12, register_width=2)
    _alert_conv_bit = RWBit(_DIAG_ALRT, 14, register_width=2)
    _vbus_ct = RWBits(3, _ADC_CONFIG, 9, register_width=2)
    _vshunt_ct = RWBits(3, _ADC_CONFIG, 6, register_width=2)
    _temper_ct = RWBits(3, _ADC_CONFIG, 3, register_width=2)
    _avg_count = RWBits(3, _ADC_CONFIG, 0, register_width=2)
    _device_id = UnaryStruct(_DEVICE_ID, ">H")
    _temperature = UnaryStruct(_DIETEMP, ">h")
    _sovl = UnaryStruct(_SOVL, ">H")  # Shunt overvoltage
    _suvl = UnaryStruct(_SUVL, ">H")  # Shunt undervoltage
    _bovl = UnaryStruct(_BOVL, ">H")  # Bus overvoltage
    _buvl = UnaryStruct(_BUVL, ">H")  # Bus undervoltage
    _temp_limit = UnaryStruct(_TEMP_LIMIT, ">H")  # Temperature limit
    _pwr_limit = UnaryStruct(_PWR_LIMIT, ">H")  # Power limit
    _shunt_tempco = UnaryStruct(_SHUNT_TEMPCO, ">H")
    """Manufacturer ID"""
    manufacturer_id = UnaryStruct(_MFG_ID, ">H")

    def __init__(self, i2c_bus, addr=0x40):
        self.i2c_device = I2CDevice(i2c_bus, addr)
        self.buf3 = bytearray(3)  # Buffer for 24-bit registers
        self.buf5 = bytearray(5)  # Buffer for 40-bit registers
        # Verify manufacturer ID (should be 0x5449 for Texas Instruments)
        if self.manufacturer_id != 0x5449:
            raise RuntimeError(
                f"Invalid manufacturer ID: 0x{self.manufacturer_id:04X} (expected 0x5449)"
            )
        # Verify device ID
        dev_id = (self._device_id >> 4) & 0xFFF
        if dev_id != 0x228:
            raise RuntimeError(f"Failed to find INA228 - check your wiring! (Got ID: 0x{dev_id:X})")
        self._current_lsb = 0
        self._shunt_res = 0
        self.reset()
        self.mode = Mode.CONTINUOUS_ALL
        self.set_shunt(0.015, 10.0)
        self.conversion_time_bus = 150
        self.conversion_time_shunt = 280
        self.averaging_count = 16

    def reset(self) -> None:
        """Reset the INA228 (all registers to default values)"""
        self._reset_bit = True
        self._alert_conv_bit = True
        self.mode = Mode.CONTINUOUS_ALL
        time.sleep(0.002)

    def _reg24(self, reg):
        """Read 24-bit register"""
        with self.i2c_device as i2c:
            i2c.write_then_readinto(bytes([reg]), self.buf3)
        result = (self.buf3[0] << 16) | (self.buf3[1] << 8) | self.buf3[2]
        return result

    def _reg40(self, reg):
        """Read 40-bit register"""
        with self.i2c_device as i2c:
            i2c.write_then_readinto(bytes([reg]), self.buf5)
        result = 0
        for b in self.buf5:
            result = (result << 8) | b
        return result

    def reset_accumulators(self) -> None:
        """Reset the energy and charge accumulators"""
        self._reset_accumulators_bit = True

    @property
    def adc_range(self) -> int:
        """
        ADC range.
        0 = ±163.84 mV
        1 = ±40.96 mV

        When using the ±40.96 mV range, the shunt calibration value is automatically scaled by 4.
        """
        return self._adc_range

    @adc_range.setter
    def adc_range(self, value: int):
        if value not in {0, 1}:
            raise ValueError("ADC range must be 0 (±163.84 mV) or 1 (±40.96 mV)")
        self._adc_range = value
        self._update_calibration()

    @property
    def alert_type(self) -> int:
        """
        The alert trigger type. Use AlertType constants.
        Can be OR'd together for multiple triggers.

        Example:
            # Single alert type
            sensor.alert_type = AlertType.OVERPOWER

            # Multiple alert types
            sensor.alert_type = AlertType.OVERPOWER | AlertType.OVERVOLTAGE
        """
        return self._alert_type

    @alert_type.setter
    def alert_type(self, value: int):
        # Check if it's a valid combination of alert types
        if value < 0 or value > AlertType._MAX_COMBINED:
            raise ValueError(f"Invalid alert type value: {value}. Must be 0-0x3F")

        # Optional: Validate that only valid bits are set
        valid_mask = (
            AlertType.CONVERSION_READY
            | AlertType.OVERPOWER
            | AlertType.UNDERVOLTAGE
            | AlertType.OVERVOLTAGE
            | AlertType.UNDERCURRENT
            | AlertType.OVERCURRENT
        )

        if value & ~valid_mask:
            raise ValueError(f"Invalid alert type bits set: 0x{value:02X}")

        self._alert_type = value

    @property
    def conversion_time_bus(self) -> int:
        """
        Bus voltage conversion time in microseconds.
        Valid values are: 50, 84, 150, 280, 540, 1052, 2074, 4120.
        """
        times = [50, 84, 150, 280, 540, 1052, 2074, 4120]
        return times[self._vbus_ct]

    @conversion_time_bus.setter
    def conversion_time_bus(self, usec: int):
        times = [50, 84, 150, 280, 540, 1052, 2074, 4120]
        if usec not in times:
            raise ValueError(
                f"Invalid conversion time: {usec}. Valid values are: {', '.join(map(str, times))}."
            )
        self._vbus_ct = times.index(usec)

    @property
    def conversion_time_shunt(self) -> int:
        """
        Shunt voltage conversion time in microseconds.
        Valid values are: 50, 84, 150, 280, 540, 1052, 2074, 4120.
        """
        times = [50, 84, 150, 280, 540, 1052, 2074, 4120]
        return times[self._vshunt_ct]

    @conversion_time_shunt.setter
    def conversion_time_shunt(self, usec: int):
        times = [50, 84, 150, 280, 540, 1052, 2074, 4120]
        if usec not in times:
            raise ValueError(
                f"Invalid conversion time: {usec}. Valid values are: {', '.join(map(str, times))}."
            )
        self._vshunt_ct = times.index(usec)

    @property
    def averaging_count(self) -> int:
        """
        Number of samples to average. Returns actual count.
        Valid values are: 1, 4, 16, 64, 128, 256, 512, 1024.
        """
        counts = [1, 4, 16, 64, 128, 256, 512, 1024]
        return counts[self._avg_count]

    @averaging_count.setter
    def averaging_count(self, count: int):
        counts = [1, 4, 16, 64, 128, 256, 512, 1024]
        if count not in counts:
            raise ValueError(
                "Invalid averaging count: "
                + str(count)
                + ". "
                + "Valid values are: "
                + ", ".join(map(str, counts))
                + "."
            )
        self._avg_count = counts.index(count)

    def set_shunt(self, shunt_res: float, max_current: float) -> None:
        """Configure shunt resistor value and maximum expected current"""
        self._shunt_res = shunt_res
        self._current_lsb = max_current / (1 << 19)
        self._update_calibration()
        time.sleep(0.001)

    def _update_calibration(self):
        """Update the calibration register based on shunt and current settings"""
        scale = 4 if self._adc_range else 1
        cal_value = int(13107.2 * 1000000.0 * self._shunt_res * self._current_lsb * scale)
        self._shunt_cal = cal_value
        read_cal = self._shunt_cal
        if read_cal != cal_value:
            raise ValueError("  Warning: Calibration readback mismatch!")

    def set_calibration_32V_2A(self) -> None:
        """Configure for 32V and up to 2A measurements"""
        self._mode = Mode.CONTINUOUS_ALL
        time.sleep(0.001)
        self.set_shunt(0.015, 10.0)
        self._vbus_ct = 5
        self._vshunt_ct = 5
        self._temper_ct = 5
        self._avg_count = 0

    def set_calibration_32V_1A(self) -> None:
        """Configure for 32V and up to 1A measurements"""
        self.set_shunt(0.1, 1.0)

    def set_calibration_16V_400mA(self) -> None:
        """Configure for 16V and up to 400mA measurements"""
        self.set_shunt(0.1, 0.4)

    @property
    def conversion_ready(self) -> bool:
        """Check if conversion is ready"""
        return bool(self._diag_alrt & (1 << 1))

    @property
    def shunt_voltage(self) -> float:
        """Shunt voltage in V"""
        raw = self._reg24(_VSHUNT)
        if raw & 0x800000:
            raw -= 0x1000000
        scale = 78.125e-9 if self._adc_range else 312.5e-9
        return (raw / 16.0) * scale

    @property
    def voltage(self) -> float:
        """Bus voltage measurement in V"""
        raw = self._reg24(_VBUS)
        value = (raw >> 4) * 195.3125e-6
        return value

    @property
    def power(self) -> float:
        """Power measurement in mW"""
        raw = self._reg24(_POWER)
        value = raw * 3.2 * self._current_lsb * 1000
        return value

    @property
    def energy(self) -> float:
        """Energy measurement in Joules"""
        raw = self._reg40(_ENERGY)
        value = raw * 16.0 * 3.2 * self._current_lsb
        return value

    @property
    def current(self) -> float:
        """Current measurement in mA"""
        raw = self._reg24(_CURRENT)
        if raw & 0x800000:
            raw -= 0x1000000
        value = (raw / 16.0) * self._current_lsb * 1000.0
        return value

    @property
    def charge(self) -> float:
        """Accumulated charge in coulombs"""
        raw = self._reg40(_CHARGE)
        if raw & (1 << 39):
            raw |= -1 << 40
        return raw * self._current_lsb

    @property
    def temperature(self) -> float:
        """Die temperature in celsius"""
        return self._temperature * 7.8125e-3

    @property
    def shunt_tempco(self) -> int:
        """Shunt temperature coefficient in ppm/°C"""
        return self._shunt_tempco

    @shunt_tempco.setter
    def shunt_tempco(self, value: int):
        self._shunt_tempco = value

    @property
    def conversion_time_temperature(self) -> int:
        """
        Temperature conversion time in microseconds.
        Valid values are: 50, 84, 150, 280, 540, 1052, 2074, 4120.
        """
        times = [50, 84, 150, 280, 540, 1052, 2074, 4120]
        return times[self._temper_ct]

    @conversion_time_temperature.setter
    def conversion_time_temperature(self, usec: int):
        times = [50, 84, 150, 280, 540, 1052, 2074, 4120]
        if usec not in times:
            raise ValueError(
                f"Invalid conversion time: {usec}. Valid values are: {', '.join(map(str, times))}."
            )
        self._temper_ct = times.index(usec)

    @property
    def alert_latch(self) -> bool:
        """Alert latch setting. True=latched, False=transparent"""
        return bool(self._alert_latch_bit)

    @alert_latch.setter
    def alert_latch(self, value: bool):
        self._alert_latch_bit = value

    @property
    def alert_polarity(self) -> bool:
        """Alert polarity. True=inverted, False=normal"""
        return bool(self._alert_polarity_bit)

    @alert_polarity.setter
    def alert_polarity(self, value: bool):
        self._alert_polarity_bit = value

    @property
    def shunt_voltage_overlimit(self) -> float:
        """Shunt voltage overlimit threshold in volts"""
        return self._sovl * (78.125e-6 if self._adc_range else 312.5e-6)

    @shunt_voltage_overlimit.setter
    def shunt_voltage_overlimit(self, value: float):
        scale = 78.125e-6 if self._adc_range else 312.5e-6
        self._sovl = int(value / scale)

    @property
    def alert_flags(self) -> dict:
        """
        All diagnostic and alert flags

        Returns a dictionary with the status of each flag:

        'ENERGYOF': bool,  # Energy overflow

        'CHARGEOF': bool,  # Charge overflow

        'MATHOF': bool,    # Math overflow

        'TMPOL': bool,     # Temperature overlimit

        'SHNTOL': bool,    # Shunt voltage overlimit

        'SHNTUL': bool,    # Shunt voltage underlimit

        'BUSOL': bool,     # Bus voltage overlimit

        'BUSUL': bool,     # Bus voltage underlimit

        'POL': bool,       # Power overlimit

        'CNVRF': bool,     # Conversion ready

        'MEMSTAT': bool,   # ADC conversion status
        """
        flags = self._diag_alrt
        return {
            "ENERGYOF": bool(flags & (1 << 11)),
            "CHARGEOF": bool(flags & (1 << 10)),
            "MATHOF": bool(flags & (1 << 9)),
            "TMPOL": bool(flags & (1 << 7)),
            "SHNTOL": bool(flags & (1 << 6)),
            "SHNTUL": bool(flags & (1 << 5)),
            "BUSOL": bool(flags & (1 << 4)),
            "BUSUL": bool(flags & (1 << 3)),
            "POL": bool(flags & (1 << 2)),
            "CNVRF": bool(flags & (1 << 1)),
            "MEMSTAT": bool(flags & (1 << 0)),
        }

    def trigger_measurement(self) -> None:
        """Trigger a one-shot measurement when in triggered mode"""
        current_mode = self.mode
        if current_mode < Mode.SHUTDOWN2:
            self.mode = current_mode

    def clear_overflow_flags(self) -> None:
        """Clear energy, charge, and math overflow flags"""
        flags = self._diag_alrt
        self._diag_alrt = flags & ~((1 << 11) | (1 << 10) | (1 << 9))
