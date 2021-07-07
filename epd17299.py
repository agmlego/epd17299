#!/usr/bin/python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: FAFOL

import pigpio
import enum

# Main SPI pins
SCK_PIN = 11
SDO_PIN = 10  # Per https://www.oshwa.org/a-resolution-to-redefine-spi-signal-names/

# Main hardware SPI CS pins; however we are going to use them as GPIO
M1_CS_PIN = 8
S1_CS_PIN = 7

# Aux hardware SPI CS pins; however, we are going to use them as GPIO
M2_CS_PIN = 17
S2_CS_PIN = 18

# GPIO for data/command lines for pairs of displays
M1S1_DC_PIN = 13
M2S2_DC_PIN = 22

# GPIO for reset lines for pairs of displays
M1S1_RST_PIN = 6
M2S2_RST_PIN = 23

# GPIO for individual display busy pins
M1_BUSY_PIN = 5
S1_BUSY_PIN = 19
M2_BUSY_PIN = 27
S2_BUSY_PIN = 24


class SPIPort(enum.Enum):
    MAIN = 0
    AUXILIARY = 1


class SPIMode(enum.Enum):
    MODE_0 = (0, 0)
    MODE_1 = (0, 1)
    MODE_2 = (1, 0)
    MODE_3 = (1, 1)


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


class spi():
    """Wrapper for a SPI bus connection, using hardware SDO/SCK but software CS#

    Keyword arguments:
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

    def __init__(self, pi, speed,
                 channel=0,
                 bus=SPIPort.MAIN,
                 busmode=SPIMode.MODE_0,
                 cspol=(SPICSPol.ACTIVE_LOW, SPICSPol.ACTIVE_LOW,
                        SPICSPol.ACTIVE_LOW),
                 hwcs=(SPIHWCS.SPI_USE, SPIHWCS.SPI_USE, SPIHWCS.SPI_USE),
                 wiremode=SPIWireMode.FOUR_WIRE,
                 threewirebytes=0,
                 txendian=SPIEndian.MSB_FIRST,
                 rxendian=SPIEndian.MSB_FIRST,
                 wordsize=8):
        self.pi = pi
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
        flags = wordsize << 16
        flags |= rxendian.value << 15
        flags |= txendian.value << 14
        flags |= threewirebytes << 10
        flags |= wiremode << 9
        flags |= bus.value << 8
        flags |= hwcs[2].value << 7 | hwcs[1].value << 6 | hwcs[0].value << 5
        flags |= cspol[2].value << 4 | cspol[1].value << 3 | cspol[0].value << 2
        flags |= busmode.value
        self._spi = self.pi.spi_open(channel, speed, flags)

    def write(self, data):
        self.pi.spi_write(self._spi, data)

    def read(self, count):
        return self.pi.spi_read(self._spi, count)


class epd17299():
    """Driver for Waveshare SKU 17299 12.48" bi-color e-ink module"""

    class Segment():
        """Wrapper for a display segment on module"""

        def __init__(self, width, height, cs, dc, rst, spi):
            self.width = width
            self.height = height
            self.

    def __init__(self):
        self.pi = pigpio.pi()
        self.pi.set_mode(7, pigpio.OUTPUT)
        self.pi.set_mode(8, pigpio.OUTPUT)
        self.pi.write(7, pigpio.HIGH)
        self.pi.write(8, pigpio.HIGH)
