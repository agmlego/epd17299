#!/usr/bin/python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: FAFOL

import contextlib
import enum
from typing import Tuple

import pigpio


class SPIPort(enum.Enum):
    MAIN = 0
    AUXILIARY = 1


class SPIMode(enum.Enum):
    MODE_0 = 0
    MODE_1 = 1
    MODE_2 = 2
    MODE_3 = 3


class PinPolarity(enum.Enum):
    ACTIVE_LOW = 0
    ACTIVE_HIGH = 1


class SPIWireMode(enum.Enum):
    THREE_WIRE = 1
    FOUR_WIRE = 0


class SPIEndian(enum.Enum):
    MSB_FIRST = 0
    LSB_FIRST = 1


def set_GPIO_active(pi, pin, polarity: PinPolarity = PinPolarity.ACTIVE_LOW):
    """Set a pin to the ACTIVE state.

    Keyword arguments:
        pi -- reference to pigpio.pi()
        pin -- GPIO pin to set
        polarity -- which polarity pin is ACTIVE in (default PinPolarity.ACTIVE_LOW)
    """
    if polarity == PinPolarity.ACTIVE_LOW:
        pi.write(pin, pigpio.LOW)
    else:
        pi.write(pin, pigpio.HIGH)


def clear_GPIO_idle(pi, pin, polarity: PinPolarity = PinPolarity.ACTIVE_LOW):
    """Clear a pin to the IDLE state.

    Keyword arguments:
        pi -- reference to pigpio.pi()
        pin -- GPIO pin to set
        polarity -- which polarity pin is ACTIVE in (default PinPolarity.ACTIVE_LOW)
    """
    if polarity == PinPolarity.ACTIVE_LOW:
        pi.write(pin, pigpio.HIGH)
    else:
        pi.write(pin, pigpio.LOW)


class SPIBus:
    """Wrapper for a SPI bus connection, using hardware SDO/SCK but software CS#

    Keyword arguments:
        pi -- reference to pigpio.pi()
        speed -- 32K-125M (values above 30M are unlikely to work)
        bus -- which SPI bus to use (default SPIPort.MAIN)
        busmode -- SPIMode for clock polarity and data phase (default SPIMode.MODE_0)
    """

    _spi = None

    def __init__(self, pi, speed,
                 bus: SPIPort = SPIPort.MAIN,
                 busmode: SPIMode = SPIMode.MODE_0
                 ):
        self.pi = pi
        self.speed = speed
        hwcs = 0b111            # disable all three hardware CS#
        cspol = 0b000           # all three polarities are irrelevant
        threewirebytes = 0b0000
        wordsize = 0b000000

        self.flags = wordsize << 16
        self.flags |= SPIEndian.MSB_FIRST.value << 15
        self.flags |= SPIEndian.MSB_FIRST.value << 14
        self.flags |= threewirebytes << 10
        self.flags |= SPIWireMode.FOUR_WIRE.value << 9
        self.flags |= bus.value << 8
        self.flags |= hwcs << 5
        self.flags |= cspol << 2
        self.flags |= busmode.value

    def __enter__(self):
        self._spi = self.pi.spi_open(0, self.speed, self.flags)
        return self

    def __exit__(self, *exc):
        self.pi.spi_close(self._spi)
        self._spi = None

    @contextlib.contextmanager
    def transaction(self, cs=0, cspol: PinPolarity = PinPolarity.ACTIVE_LOW, dc=0, dcpol: PinPolarity = PinPolarity.ACTIVE_LOW):
        """
        Construct an SPI transaction to actually talk to a device

        Usage:

        >>> with spi_bus.transaction(...) as t:
        ...     t.write(b"foobar")
        ...     data = t.read(42)
        """
        set_GPIO_active(self.pi, cs, cspol)
        yield SPITransaction(self._spi, dc, dcpol)
        clear_GPIO_idle(self.pi, cs, cspol)


class SPITransaction:
    def __init__(self, spi, dc, dcpol):
        self._spi = spi
        self.dc = dc
        self.dcpol = dcpol

    def write(self, data, command=False):
        if command:
            set_GPIO_active(self.pi, self.dc, self.dcpol)
        else:
            clear_GPIO_idle(self.pi, self.dc, self.dcpol)
        self.pi.spi_write(self._spi, data)
        clear_GPIO_idle(self.pi, self.dc, self.dcpol)


class Epd17299:
    """Driver for Waveshare SKU 17299 12.48" bi-color e-ink module"""

    class Segment:
        """Wrapper for a display segment on module

        Keyword arguments:
            pi -- reference to pigpio.pi()
            left -- leftmost pixel in overall array
            top -- topmost pixel in overall array
            width -- width of this segment in pixels
            height -- height of this segment in pixels
            cs -- GPIO pin for CS
            dc -- GPIO pin for data/command
            rst -- GPIO pin for reset
            busy -- GPIO pin for busy
        """

        def __init__(self, pi, left, top, width, height, cs, dc, rst, busy):
            self.pi = pi
            self.left = left
            self.top = top
            self.width = width
            self.height = height
            self.cs = cs
            self.dc = dc
            self.rst = rst
            self.busy = busy

            self.pi.set_mode(self.cs, pigpio.OUTPUT)
            self.pi.set_mode(self.rst, pigpio.OUTPUT)
            self.pi.set_mode(self.dc, pigpio.OUTPUT)
            self.pi.set_mode(self.busy, pigpio.INPUT)

            clear_GPIO_idle(self.pi, self.cs)
            set_GPIO_active(self.pi, self.rst)
            clear_GPIO_idle(self.pi, self.dc)

            # TODO finish init of GPIO and module

        def __enter__(self):
            self._dev = SPIBus(self.pi, speed=100000,
                               bus=SPIPort.MAIN, busmode=SPIMode.MODE_0)
            self._dev.__enter__()

        def __exit__(self, *exc):
            self._dev.__exit__(*exc)

    def __init__(self):
        self.pi = pigpio.pi()

        # Main SPI pins
        SCK_PIN = 11
        SDO_PIN = 10  # Per https://www.oshwa.org/a-resolution-to-redefine-spi-signal-names/

        self.S2 = Epd17299.Segment(self.pi, left=0, top=0, width=648,
                                   height=492, cs=18, dc=22, rst=23, busy=24)
        self.M1 = Epd17299.Segment(self.pi, left=0, top=492, width=648,
                                   height=492, cs=8, dc=13, rst=6, busy=5)
        self.S1 = Epd17299.Segment(self.pi, left=648, top=0, width=656,
                                   height=492, cs=7, dc=13, rst=6, busy=19)
        self.M2 = Epd17299.Segment(self.pi, left=648, top=492, width=656,
                                   height=492, cs=17, dc=22, rst=23, busy=27)

    def __del__(self):
        self.pi.stop()

    def __enter__(self):
        self._context_stack = contextlib.ExitStack()
        self._context_stack.__enter__()
        self.enter_context(self.S2)
        self.enter_context(self.M1)
        self.enter_context(self.S1)
        self.enter_context(self.M2)

    def __exit__(self, *exc):
        self._context_stack.__exit__(*exc)
