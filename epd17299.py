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


class SPICSPol(enum.Enum):
    ACTIVE_LOW = 0
    ACTIVE_HIGH = 1


class SPIHWCS(enum.Enum):
    SPI_USE = 0
    GPIO_USE = 1


class SPIWireMode(enum.Enum):
    THREE_WIRE = 1
    FOUR_WIRE = 0


class SPIEndian(enum.Enum):
    MSB_FIRST = 0
    LSB_FIRST = 1


class SPIDevice:
    """Wrapper for a SPI bus connection, using hardware SDO/SCK but software CS#

    Keyword arguments:
        pi -- reference to pigpio.pi()
        speed -- 32K-125M (values above 30M are unlikely to work)
        channel -- if hwcs is SPIHWCS.SPI_USE, HW CS pin 0-1 (0-2 for the auxiliary SPI), otherwise GPIO number for CS pin (default 0)
        bus -- which SPI bus to use (default SPIPort.MAIN)
        busmode -- SPIMode for clock polarity and data phase (default SPIMode.MODE_0)
        cspol -- three-tuple of CS polarity (default (SPICSPol.ACTIVE_LOW, SPICSPol.ACTIVE_LOW, SPICSPol.ACTIVE_LOW))
        hwcs -- three-tuple of whether hardware CS pins are for SPI use or GPIO use (default (SPIHWCS.SPI_USE, SPIHWCS.SPI_USE, SPIHWCS.SPI_USE))
        wiremode -- Whether peripheral is three-wire or not, main SPI only (default SPIWireMode.FOUR_WIRE)
        threewirebytes -- if wiremode is SPIWireMode.THREE_WIRE, how many bytes to tx before switching to rx, main SPI only, ignored if not SPIWireMode.THREE_WIRE (default 0)
        txendian -- Whether MSB or LSB should be transmitted first, auxiliary SPI only (default SPIEndian.MSB_FIRST)
        rxendian -- Whether MSB or LSB should be received first, auxiliary SPI only (default SPIEndian.MSB_FIRST)
        wordsize -- number of bits to make a word, 8-40, auxiliary SPI only (default 8)
    """

    _spi = None

    def __init__(self, pi, speed,
                 channel=0,
                 bus: SPIPort = SPIPort.MAIN,
                 busmode: SPIMode = SPIMode.MODE_0,
                 cspol: Tuple[SPICSPol, SPICSPol, SPICSPol] =
                 (SPICSPol.ACTIVE_LOW, SPICSPol.ACTIVE_LOW, SPICSPol.ACTIVE_LOW),
                 hwcs: Tuple[SPIHWCS, SPIHWCS, SPIHWCS] =
                 (SPIHWCS.SPI_USE, SPIHWCS.SPI_USE, SPIHWCS.SPI_USE),
                 wiremode: SPIWireMode = SPIWireMode.FOUR_WIRE,
                 threewirebytes=0,
                 txendian: SPIEndian = SPIEndian.MSB_FIRST,
                 rxendian: SPIEndian = SPIEndian.MSB_FIRST,
                 wordsize=8,
                 ):
        self.pi = pi
        self.speed = speed
        self.cs = channel
        if bus == SPIPort.MAIN:
            if hwcs == SPIHWCS.SPI_USE and channel not in range(2):
                raise ValueError(
                    f'Channel on main SPI bus with HW CS must be [0-1], not {channel}')
            if wiremode == SPIWireMode.THREE_WIRE and threewirebytes not in range(16):
                raise ValueError(
                    f'Three-wire bytes must be [0-15], not {threewirebytes}')
            if wiremode == SPIWireMode.FOUR_WIRE:
                threewirebytes = 0
            txendian = SPIEndian.MSB_FIRST
            rxendian = SPIEndian.MSB_FIRST
            wordsize = 8
        else:
            if hwcs == SPIHWCS.SPI_USE and channel not in range(3):
                raise ValueError(
                    f'Channel on auxiliary SPI bus with HW CS must be [0-2], not {channel}')
            if busmode == SPIMode.MODE_1 or busmode == SPIMode.MODE_3:
                raise ValueError(
                    f'Modes 1 and 3 do not work on auxiliary SPI bus: {busmode}')
            if wordsize not in range(8, 41):
                raise ValueError(
                    f'Word size must be in [8-40], not {wordsize}')
            wiremode = SPIWireMode.FOUR_WIRE
            threewirebytes = 0

        if hwcs == SPIHWCS.GPIO_USE:
            channel = 0

        wordsize -= 8
        self.flags = wordsize << 16
        self.flags |= rxendian.value << 15
        self.flags |= txendian.value << 14
        self.flags |= threewirebytes << 10
        self.flags |= wiremode << 9
        self.flags |= bus.value << 8
        self.flags |= hwcs[2].value << 7 | hwcs[1].value << 6 | hwcs[0].value << 5
        self.flags |= cspol[2].value << 4 | cspol[1].value << 3 | cspol[0].value << 2
        self.flags |= busmode.value

    def __enter__(self):
        self._spi = self.pi.spi_open(self.cs, self.speed, self.flags)
        return self

    def __exit__(self, *exc):
        self.pi.spi_close(self._spi)
        self._spi = None

    def write(self, data):
        self.pi.spi_write(self._spi, data)

    def read(self, count):
        return self.pi.spi_read(self._spi, count)


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
            self.pi.write(self.cs, pigpio.HIGH)

            #TODO finish init of GPIO

        def __enter__(self):
            self._dev = SPIDevice(self.pi,speed=100000,channel=0,bus=SPIPort.MAIN,busmode=SPIMode.MODE_0)
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
