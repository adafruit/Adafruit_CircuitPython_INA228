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

* `Adafruit INA228 High or Low Side Current and Power Monitor <https://www.adafruit.com/product/5832>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards: https://circuitpython.org/downloads

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
* Adafruit's Register library: https://github.com/adafruit/Adafruit_CircuitPython_Register
"""

import time

from adafruit_bus_device.i2c_device import I2CDevice
from adafruit_register.i2c_bit import ROBit, RWBit
from adafruit_register.i2c_bits import ROBits, RWBits
from adafruit_register.i2c_struct import ROUnaryStruct, UnaryStruct
from micropython import const

try:
    import typing

    from busio import I2C
except ImportError:
    pass

__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_INA228.git"

# Common register addresses for INA2XX family
_CONFIG = const(0x00)
_ADCCFG = const(0x01)
_SHUNTCAL = const(0x02)
_VSHUNT = const(0x04)
_VBUS = const(0x05)
_DIETEMP = const(0x06)
_CURRENT = const(0x07)
_POWER = const(0x08)
_DIAGALRT = const(0x0B)
_MFG_UID = const(0x3E)
_DVC_UID = const(0x3F)

# INA228-specific registers
_SHUNT_TEMPCO = const(0x03)
_ENERGY = const(0x09)
_CHARGE = const(0x0A)
_SOVL = const(0x0C)
_SUVL = const(0x0D)
_BOVL = const(0x0E)
_BUVL = const(0x0F)
_TEMP_LIMIT = const(0x10)
_PWR_LIMIT = const(0x11)

# Constants
_INA2XX_DEFAULT_ADDR = const(0x40)
_TEXAS_INSTRUMENTS_ID = const(0x5449)
_INA228_DEVICE_ID = const(0x228)


class Mode:
    """Operating mode constants for INA2XX"""

    SHUTDOWN = const(0x00)
    TRIG_BUS = const(0x01)
    TRIG_SHUNT = const(0x02)
    TRIG_BUS_SHUNT = const(0x03)
    TRIG_TEMP = const(0x04)
    TRIG_TEMP_BUS = const(0x05)
    TRIG_TEMP_SHUNT = const(0x06)
    TRIG_TEMP_BUS_SHUNT = const(0x07)
    CONT_BUS = const(0x09)
    CONT_SHUNT = const(0x0A)
    CONT_BUS_SHUNT = const(0x0B)
    CONT_TEMP = const(0x0C)
    CONT_TEMP_BUS = const(0x0D)
    CONT_TEMP_SHUNT = const(0x0E)
    CONT_TEMP_BUS_SHUNT = const(0x0F)

    # Convenience aliases
    TRIGGERED = TRIG_TEMP_BUS_SHUNT
    CONTINUOUS = CONT_TEMP_BUS_SHUNT

    # Valid modes set for validation
    _VALID_MODES = {
        SHUTDOWN,
        TRIG_BUS,
        TRIG_SHUNT,
        TRIG_BUS_SHUNT,
        TRIG_TEMP,
        TRIG_TEMP_BUS,
        TRIG_TEMP_SHUNT,
        TRIG_TEMP_BUS_SHUNT,
        CONT_BUS,
        CONT_SHUNT,
        CONT_BUS_SHUNT,
        CONT_TEMP,
        CONT_TEMP_BUS,
        CONT_TEMP_SHUNT,
        CONT_TEMP_BUS_SHUNT,
    }


class ConversionTime:
    """Conversion time constants for INA2XX"""

    TIME_50_US = const(0)
    TIME_84_US = const(1)
    TIME_150_US = const(2)
    TIME_280_US = const(3)
    TIME_540_US = const(4)
    TIME_1052_US = const(5)
    TIME_2074_US = const(6)
    TIME_4120_US = const(7)

    _VALID_TIMES = {
        TIME_50_US,
        TIME_84_US,
        TIME_150_US,
        TIME_280_US,
        TIME_540_US,
        TIME_1052_US,
        TIME_2074_US,
        TIME_4120_US,
    }

    # Microsecond values for each setting
    _VALUES = [50, 84, 150, 280, 540, 1052, 2074, 4120]


class AveragingCount:
    """Averaging count constants for INA2XX"""

    COUNT_1 = const(0)
    COUNT_4 = const(1)
    COUNT_16 = const(2)
    COUNT_64 = const(3)
    COUNT_128 = const(4)
    COUNT_256 = const(5)
    COUNT_512 = const(6)
    COUNT_1024 = const(7)

    _VALID_COUNTS = {
        COUNT_1,
        COUNT_4,
        COUNT_16,
        COUNT_64,
        COUNT_128,
        COUNT_256,
        COUNT_512,
        COUNT_1024,
    }

    # Actual count values for each setting
    _VALUES = [1, 4, 16, 64, 128, 256, 512, 1024]


class AlertType:
    """Alert type constants for INA2XX"""

    NONE = const(0x0)
    CONVERSION_READY = const(0x1)
    OVERPOWER = const(0x2)
    UNDERVOLTAGE = const(0x4)
    OVERVOLTAGE = const(0x8)
    UNDERCURRENT = const(0x10)
    OVERCURRENT = const(0x20)

    # INA237/238 specific
    OVERTEMPERATURE = const(0x2)
    UNDERSHUNT = const(0x20)
    OVERSHUNT = const(0x40)

    _VALID_TYPES = {
        NONE,
        CONVERSION_READY,
        OVERPOWER,
        UNDERVOLTAGE,
        OVERVOLTAGE,
        UNDERCURRENT,
        OVERCURRENT,
        OVERTEMPERATURE,
        UNDERSHUNT,
        OVERSHUNT,
    }


class INA2XX:  # noqa: PLR0904
    """Base driver for INA2XX series power and current sensors.

    :param ~busio.I2C i2c_bus: The I2C bus the INA2XX is connected to.
    :param int address: The I2C device address. Defaults to :const:`0x40`
    :param bool skip_reset: Skip resetting the device on init. Defaults to False.
    """

    # Configuration register bits
    _reset = RWBit(_CONFIG, 15, register_width=2, lsb_first=False)
    _adc_range = RWBit(_CONFIG, 4, register_width=2, lsb_first=False)

    # ADC Configuration register bits
    _mode = RWBits(4, _ADCCFG, 12, register_width=2, lsb_first=False)
    _vbus_conv_time = RWBits(3, _ADCCFG, 9, register_width=2, lsb_first=False)
    _vshunt_conv_time = RWBits(3, _ADCCFG, 6, register_width=2, lsb_first=False)
    _temp_conv_time = RWBits(3, _ADCCFG, 3, register_width=2, lsb_first=False)
    _avg_count = RWBits(3, _ADCCFG, 0, register_width=2, lsb_first=False)

    # Diagnostic/Alert register bits
    _alert_latch = RWBit(_DIAGALRT, 15, register_width=2, lsb_first=False)
    _alert_conv = RWBit(_DIAGALRT, 14, register_width=2, lsb_first=False)
    _alert_polarity = RWBit(_DIAGALRT, 12, register_width=2, lsb_first=False)

    # Measurement registers
    _raw_dietemp = ROUnaryStruct(_DIETEMP, ">h")
    _raw_vbus = ROUnaryStruct(_VBUS, ">H")

    # Calibration register
    _shunt_cal = UnaryStruct(_SHUNTCAL, ">H")

    # ID registers
    _manufacturer_id = ROUnaryStruct(_MFG_UID, ">H")
    _device_id = ROUnaryStruct(_DVC_UID, ">H")

    def __init__(
        self, i2c_bus: I2C, address: int = _INA2XX_DEFAULT_ADDR, skip_reset: bool = False
    ) -> None:
        self.i2c_device = I2CDevice(i2c_bus, address)

        # Verify manufacturer ID
        if self._manufacturer_id != _TEXAS_INSTRUMENTS_ID:
            raise ValueError("Failed to find INA2XX - incorrect manufacturer ID")

        self._shunt_res = 0.1  # Default shunt resistance
        self._current_lsb = 0.0

        if not skip_reset:
            self.reset()
            time.sleep(0.002)  # 2ms delay for first measurement

        # Set defaults
        self.averaging_count = AveragingCount.COUNT_16
        self.bus_voltage_conv_time = ConversionTime.TIME_150_US
        self.shunt_voltage_conv_time = ConversionTime.TIME_280_US
        self.mode = Mode.CONTINUOUS

    def reset(self) -> None:
        """Reset the sensor to default configuration."""
        self._reset = True
        self._alert_conv = True
        self.mode = Mode.CONTINUOUS

    @property
    def device_id(self) -> int:
        """Device ID"""
        return (self._device_id >> 4) & 0xFFF

    @property
    def shunt_resistance(self) -> float:
        """The shunt resistance in ohms."""
        return self._shunt_res

    @property
    def adc_range(self) -> int:
        """ADC range setting. 0 = ±163.84mV, 1 = ±40.96mV"""
        return self._adc_range

    @adc_range.setter
    def adc_range(self, value: int) -> None:
        if value not in {0, 1}:
            raise ValueError("ADC range must be 0 or 1")
        self._adc_range = value
        self._update_shunt_cal()

    @property
    def mode(self) -> int:
        """Operating mode of the sensor."""
        return self._mode

    @mode.setter
    def mode(self, value: int) -> None:
        if value not in Mode._VALID_MODES:
            raise ValueError(f"Invalid mode 0x{value:02X}. Must be one of the Mode.* constants")
        self._mode = value

    @property
    def averaging_count(self) -> int:
        """Number of samples to average."""
        return self._avg_count

    @averaging_count.setter
    def averaging_count(self, value: int) -> None:
        if value not in AveragingCount._VALID_COUNTS:
            raise ValueError(
                f"Invalid averaging count {value}. Must be one of the AveragingCount.* constants"
            )
        self._avg_count = value

    @property
    def bus_voltage_conv_time(self) -> int:
        """Bus voltage conversion time setting."""
        return self._vbus_conv_time

    @bus_voltage_conv_time.setter
    def bus_voltage_conv_time(self, value: int) -> None:
        if value not in ConversionTime._VALID_TIMES:
            raise ValueError(
                f"Invalid conversion time {value}. Must be one of the ConversionTime.* constants"
            )
        self._vbus_conv_time = value

    @property
    def shunt_voltage_conv_time(self) -> int:
        """Shunt voltage conversion time setting."""
        return self._vshunt_conv_time

    @shunt_voltage_conv_time.setter
    def shunt_voltage_conv_time(self, value: int) -> None:
        if value not in ConversionTime._VALID_TIMES:
            raise ValueError(
                f"Invalid conversion time {value}. Must be one of the ConversionTime.* constants"
            )
        self._vshunt_conv_time = value

    @property
    def temp_conv_time(self) -> int:
        """Temperature conversion time setting."""
        return self._temp_conv_time

    @temp_conv_time.setter
    def temp_conv_time(self, value: int) -> None:
        if value not in ConversionTime._VALID_TIMES:
            raise ValueError(
                f"Invalid conversion time {value}. Must be one of the ConversionTime.* constants"
            )
        self._temp_conv_time = value

    @property
    def alert_polarity(self) -> int:
        """Alert pin polarity. 0 = active high, 1 = active low."""
        return self._alert_polarity

    @alert_polarity.setter
    def alert_polarity(self, value: int) -> None:
        if value not in {0, 1}:
            raise ValueError("Alert polarity must be 0 or 1")
        self._alert_polarity = value

    @property
    def alert_latch(self) -> int:
        """Alert latch enable. 0 = transparent, 1 = latched."""
        return self._alert_latch

    @alert_latch.setter
    def alert_latch(self, value: int) -> None:
        if value not in {0, 1}:
            raise ValueError("Alert latch must be 0 or 1")
        self._alert_latch = value


class INA228(INA2XX):  # noqa: PLR0904
    """Driver for the INA228 power and current sensor"""

    # Additional registers for INA228
    _reset_accumulators_bit = RWBit(_CONFIG, 14, register_width=2, lsb_first=False)
    _alert_type = RWBits(6, _DIAGALRT, 8, register_width=2, lsb_first=False)
    _alert_flags = ROUnaryStruct(_DIAGALRT, ">H")

    _shunt_tempco = UnaryStruct(_SHUNT_TEMPCO, ">H")
    _sovl = UnaryStruct(_SOVL, ">H")
    _suvl = UnaryStruct(_SUVL, ">H")
    _bovl = UnaryStruct(_BOVL, ">H")
    _buvl = UnaryStruct(_BUVL, ">H")
    _temp_limit = UnaryStruct(_TEMP_LIMIT, ">H")
    _pwr_limit = UnaryStruct(_PWR_LIMIT, ">H")

    _raw_vshunt = ROUnaryStruct(_VSHUNT, ">h")
    _raw_current = ROUnaryStruct(_CURRENT, ">h")
    _raw_power = ROUnaryStruct(_POWER, ">H")

    _conversion_ready = ROBit(_DIAGALRT, 1, register_width=2, lsb_first=False)

    def __init__(self, i2c_bus: I2C, address: int = 0x40, skip_reset: bool = False) -> None:
        # Initialize 24-bit and 40-bit register buffers
        self.buf3 = bytearray(3)  # Buffer for 24-bit registers
        self.buf5 = bytearray(5)  # Buffer for 40-bit registers

        super().__init__(i2c_bus, address, skip_reset)

        # Verify device ID
        dev_id = self.device_id
        if dev_id != _INA228_DEVICE_ID:
            raise RuntimeError(f"Failed to find INA228 - check your wiring! (Got ID: 0x{dev_id:X})")

        # Set INA228 defaults
        self.set_calibration(0.015, 10.0)

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

    def set_calibration(self, shunt_res: float = 0.015, max_current: float = 10.0) -> None:
        """Set the calibration based on shunt resistance and maximum expected current.

        :param float shunt_res: Shunt resistance in ohms
        :param float max_current: Maximum expected current in amperes
        """
        self._shunt_res = shunt_res
        # INA228 uses 2^19 as divisor
        self._current_lsb = max_current / (1 << 19)
        self._update_shunt_cal()
        time.sleep(0.001)

    def _update_shunt_cal(self) -> None:
        """Update the shunt calibration register."""
        scale = 4 if self._adc_range else 1
        # INA228 formula: SHUNT_CAL = 13107.2 × 10^6 × CURRENT_LSB × RSHUNT × scale
        cal_value = int(13107.2 * 1000000.0 * self._shunt_res * self._current_lsb * scale)
        self._shunt_cal = cal_value

    @property
    def die_temperature(self) -> float:
        """Die temperature in degrees Celsius."""
        # INA228 uses 7.8125 m°C/LSB
        return self._raw_dietemp * 7.8125e-3

    @property
    def bus_voltage(self) -> float:
        """Bus voltage in volts."""
        raw = self._reg24(_VBUS)
        # INA228 uses 195.3125 µV/LSB
        return (raw >> 4) * 195.3125e-6

    @property
    def shunt_voltage(self) -> float:
        """Shunt voltage in volts."""
        raw = self._reg24(_VSHUNT)
        if raw & 0x800000:
            raw -= 0x1000000
        # Scale depends on ADC range
        scale = 78.125e-9 if self._adc_range else 312.5e-9
        return (raw / 16.0) * scale

    @property
    def current(self) -> float:
        """Current in amperes."""
        raw = self._reg24(_CURRENT)
        if raw & 0x800000:
            raw -= 0x1000000
        return (raw / 16.0) * self._current_lsb

    @property
    def power(self) -> float:
        """Power in watts."""
        raw = self._reg24(_POWER)
        # INA228 power LSB = 3.2 × current_lsb
        return raw * 3.2 * self._current_lsb

    @property
    def energy(self) -> float:
        """Energy measurement in Joules"""
        raw = self._reg40(_ENERGY)
        return raw * 16.0 * 3.2 * self._current_lsb

    @property
    def charge(self) -> float:
        """Accumulated charge in coulombs"""
        raw = self._reg40(_CHARGE)
        if raw & (1 << 39):
            raw |= -1 << 40
        return raw * self._current_lsb

    @property
    def conversion_ready(self) -> bool:
        """Check if conversion is complete."""
        return bool(self._conversion_ready)

    @property
    def alert_type(self) -> int:
        """Alert type configuration."""
        return self._alert_type

    @alert_type.setter
    def alert_type(self, value: int) -> None:
        # Alert type can be a combination of flags
        valid_mask = (
            AlertType.CONVERSION_READY
            | AlertType.OVERPOWER
            | AlertType.UNDERVOLTAGE
            | AlertType.OVERVOLTAGE
            | AlertType.UNDERCURRENT
            | AlertType.OVERCURRENT
        )
        if value & ~valid_mask:
            raise ValueError(
                f"Invalid alert type 0x{value:02X}. Must be a combination of AlertType.* constants"
            )
        self._alert_type = value

    @property
    def alert_flags(self) -> dict:
        """
        All diagnostic and alert flags

        Returns a dictionary with the status of each flag:
        - 'ENERGYOF': bool - Energy overflow
        - 'CHARGEOF': bool - Charge overflow
        - 'MATHOF': bool - Math overflow
        - 'TMPOL': bool - Temperature overlimit
        - 'SHNTOL': bool - Shunt voltage overlimit
        - 'SHNTUL': bool - Shunt voltage underlimit
        - 'BUSOL': bool - Bus voltage overlimit
        - 'BUSUL': bool - Bus voltage underlimit
        - 'POL': bool - Power overlimit
        - 'CNVRF': bool - Conversion ready
        - 'MEMSTAT': bool - ADC conversion status
        """
        flags = self._alert_flags
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

    @property
    def shunt_tempco(self) -> int:
        """Shunt temperature coefficient in ppm/°C"""
        return self._shunt_tempco

    @shunt_tempco.setter
    def shunt_tempco(self, value: int):
        self._shunt_tempco = value

    @property
    def shunt_voltage_overlimit(self) -> float:
        """Shunt voltage overlimit threshold in volts"""
        return self._sovl * (78.125e-6 if self._adc_range else 312.5e-6)

    @shunt_voltage_overlimit.setter
    def shunt_voltage_overlimit(self, value: float):
        scale = 78.125e-6 if self._adc_range else 312.5e-6
        self._sovl = int(value / scale)

    @property
    def shunt_voltage_underlimit(self) -> float:
        """Shunt voltage underlimit threshold in volts"""
        return self._suvl * (78.125e-6 if self._adc_range else 312.5e-6)

    @shunt_voltage_underlimit.setter
    def shunt_voltage_underlimit(self, value: float):
        scale = 78.125e-6 if self._adc_range else 312.5e-6
        self._suvl = int(value / scale)

    @property
    def bus_voltage_overlimit(self) -> float:
        """Bus voltage overlimit threshold in volts"""
        return self._bovl * 3.125e-3

    @bus_voltage_overlimit.setter
    def bus_voltage_overlimit(self, value: float):
        self._bovl = int(value / 3.125e-3)

    @property
    def bus_voltage_underlimit(self) -> float:
        """Bus voltage underlimit threshold in volts"""
        return self._buvl * 3.125e-3

    @bus_voltage_underlimit.setter
    def bus_voltage_underlimit(self, value: float):
        self._buvl = int(value / 3.125e-3)

    @property
    def temperature_limit(self) -> float:
        """Temperature overlimit threshold in degrees Celsius"""
        return self._temp_limit * 7.8125e-3

    @temperature_limit.setter
    def temperature_limit(self, value: float):
        self._temp_limit = int(value / 7.8125e-3)

    @property
    def power_limit(self) -> float:
        """Power overlimit threshold in watts"""
        # Power limit LSB = 256 × current_lsb × 3.2
        return self._pwr_limit * 256 * self._current_lsb * 3.2

    @power_limit.setter
    def power_limit(self, value: float):
        self._pwr_limit = int(value / (256 * self._current_lsb * 3.2))

    def trigger_measurement(self) -> None:
        """Trigger a one-shot measurement when in triggered mode"""
        current_mode = self.mode
        if current_mode <= Mode.TRIG_TEMP_BUS_SHUNT:
            # Re-write the same mode to trigger measurement
            self.mode = current_mode

    def clear_overflow_flags(self) -> None:
        """Clear energy, charge, and math overflow flags"""
        # Read-modify-write to clear only overflow flags
        flags = self._alert_flags
        self._alert_flags = flags & ~((1 << 11) | (1 << 10) | (1 << 9))

    # Convenience calibration methods
    def set_calibration_32V_2A(self) -> None:
        """Configure for 32V and up to 2A measurements"""
        self.mode = Mode.CONTINUOUS
        time.sleep(0.001)
        self.set_calibration(0.015, 10.0)
        self.bus_voltage_conv_time = ConversionTime.TIME_1052_US
        self.shunt_voltage_conv_time = ConversionTime.TIME_1052_US
        self.temp_conv_time = ConversionTime.TIME_1052_US
        self.averaging_count = AveragingCount.COUNT_1

    def set_calibration_32V_1A(self) -> None:
        """Configure for 32V and up to 1A measurements"""
        self.set_calibration(0.1, 1.0)

    def set_calibration_16V_400mA(self) -> None:
        """Configure for 16V and up to 400mA measurements"""
        self.set_calibration(0.1, 0.4)
