#!/usr/bin/python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: FAFOL

import contextlib
import enum
import logging
import struct
import time
from typing import Sequence

import pigpio
from PIL import Image

logger = logging.getLogger(__name__)


class SPIPort(enum.Enum):
    """Flags for SPI ports on the Pi"""

    MAIN = 0
    AUXILIARY = 1


class SPIMode(enum.Enum):
    """Flags for SPI modes, following convention for data and clock phase"""
    MODE_0 = 0
    MODE_1 = 1
    MODE_2 = 2
    MODE_3 = 3


class PinPolarity(enum.Enum):
    """Flags for GPIO pin polarity"""
    ACTIVE_LOW = 0
    ACTIVE_HIGH = 1


class SPIWireMode(enum.Enum):
    """Flags for SPI wire mode on the Pi"""
    THREE_WIRE = 1
    FOUR_WIRE = 0


class SPIEndian(enum.Enum):
    """Flags for SPI endianness"""
    MSB_FIRST = 0
    LSB_FIRST = 1


def set_GPIO_active(pi, pin, polarity: PinPolarity = PinPolarity.ACTIVE_LOW):
    """
    Set a GPIO pin to the ACTIVE state

    Args:
        pi (pigpio.pi()): reference to pigpio engine
        pin (integer): GPIO pin to set
        polarity (PinPolarity, optional): flag for pin polarity. Defaults to PinPolarity.ACTIVE_LOW.
    """

    if polarity == PinPolarity.ACTIVE_LOW:
        pi.write(pin, pigpio.LOW)
    else:
        pi.write(pin, pigpio.HIGH)


def clear_GPIO_idle(pi, pin, polarity: PinPolarity = PinPolarity.ACTIVE_LOW):
    """
    Clear a GPIO pin to the IDLE state

    Args:
        pi (pigpio.pi()): reference to pigpio engine
        pin (integer): GPIO pin to set
        polarity (PinPolarity, optional): flag for pin polarity. Defaults to PinPolarity.ACTIVE_LOW.
    """

    if polarity == PinPolarity.ACTIVE_LOW:
        pi.write(pin, pigpio.HIGH)
    else:
        pi.write(pin, pigpio.LOW)


class SPIBus:
    """
    Wrapper for a SPI bus connection, using hardware SDO/SCK but software CS#

    Returns:
        SPIBus: the actual wrapper

    Yields:
        SPIBus: a reference to the wrapper for use in context managers
    """

    _spi = None

    def __init__(self, pi, speed,
                 bus: SPIPort = SPIPort.MAIN,
                 busmode: SPIMode = SPIMode.MODE_0
                 ):
        """
        Create a new SPIBus wrapper

        Args:
            pi (pigpio.pi()): reference to pigpio engine
            speed (integer): bus speed 32000 - 125000000, though values over 30000000 are unlikely to work
            bus (SPIPort, optional): flag for which SPI port to use. Defaults to SPIPort.MAIN.
            busmode (SPIMode, optional): flag for which SPI mode to use. Defaults to SPIMode.MODE_0.
        """

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
    def transaction(self, cs=0, cspol: PinPolarity = PinPolarity.ACTIVE_LOW, dc=1, dcpol: PinPolarity = PinPolarity.ACTIVE_LOW):
        """
        Construct a SPI transaction to actually talk to a device

        Args:
            cs (int, optional): GPIO pin for chip select. Defaults to 0.
            cspol (PinPolarity, optional): flag for chip select polarity. Defaults to PinPolarity.ACTIVE_LOW.
            dc (int, optional): GPIO pin for data/command. Defaults to 1.
            dcpol (PinPolarity, optional): flag for data/command polarity. Defaults to PinPolarity.ACTIVE_LOW.

        Yields:
            SPITransaction: the wrapper for the transaction

        Usage:
            >>> with spi_bus.transaction(...) as t:
            ...     t.write(b"foobar")
            ...     data = t.read(42)

        """

        # TODO: do we need to do CS# for transactions, or for messages?
        set_GPIO_active(self.pi, cs, cspol)
        yield SPITransaction(self.pi, self._spi, dc, dcpol)
        clear_GPIO_idle(self.pi, cs, cspol)


class SPITransaction:
    """Wrapper for a SPI transaction."""

    def __init__(self, pi, spi, dc, dcpol):
        """Create a new SPITransaction.

        Args:
            pi (pigpio.pi()): reference to pigpio engine
            spi (SPIBus): reference to a SPIBus
            dc (integer): GPIO pin for data/command
            dcpol (PinPolarity): flag data/command polarity
        """

        self.pi = pi
        self._spi = spi
        self.dc = dc
        self.dcpol = dcpol

    def write(self, data, command=False):
        """
        Write data to the bus

        Args:
            data (bytes): the data to write
            command (bool, optional): Flag indicating command (True) or data (False). Defaults to False.
        """

        if command:
            set_GPIO_active(self.pi, self.dc, self.dcpol)
        else:
            clear_GPIO_idle(self.pi, self.dc, self.dcpol)
        if isinstance(data, Sequence):
            data = bytes(data)
        elif isinstance(data, int):
            data = bytes((data,))
        logger.debug(
            f'Writing {("DATA","COMMAND")[command]}: <{", ".join([f"0x{byte:02X}" for byte in data])}')
        self.pi.spi_write(self._spi, data)
        clear_GPIO_idle(self.pi, self.dc, self.dcpol)

    def read(self):
        """Read data from the bus"""
        raise NotImplementedError('Sorry, cannot read yet')


class Epd17299:
    """Driver for Waveshare SKU 17299 12.48" bi-color e-ink module"""

    class SegmentName(enum.Enum):
        """Names of segments"""
        M1 = 0
        S1 = 1
        M2 = 2
        S2 = 3

    class Segment:
        """Wrapper for a display segment on module"""

        _lut_vcom1 = [
            0x00,	0x10,	0x10,	0x01,	0x08,	0x01,
            0x00,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x00,	0x08,	0x01,	0x08,	0x01,	0x06,
            0x00,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x06,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x01,
            0x00,	0x04,	0x05,	0x08,	0x08,	0x01,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
        ]
        _lut_ww1 = [
            0x91,	0x10,	0x10,	0x01,	0x08,	0x01,
            0x04,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x84,	0x08,	0x01,	0x08,	0x01,	0x06,
            0x80,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x06,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x01,
            0x08,	0x04,	0x05,	0x08,	0x08,	0x01,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
        ]
        _lut_bw1 = [
            0xA8,	0x10,	0x10,	0x01,	0x08,	0x01,
            0x84,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x84,	0x08,	0x01,	0x08,	0x01,	0x06,
            0x86,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x8C,	0x05,	0x01,	0x1E,	0x0F,	0x06,
            0x8C,	0x05,	0x01,	0x1E,	0x0F,	0x01,
            0xF0,	0x04,	0x05,	0x08,	0x08,	0x01,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
        ]
        _lut_wb1 = [
            0x91,	0x10,	0x10,	0x01,	0x08,	0x01,
            0x04,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x84,	0x08,	0x01,	0x08,	0x01,	0x06,
            0x80,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x06,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x01,
            0x08,	0x04,	0x05,	0x08,	0x08,	0x01,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
        ]
        _lut_bb1 = [
            0x92,	0x10,	0x10,	0x01,	0x08,	0x01,
            0x80,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x84,	0x08,	0x01,	0x08,	0x01,	0x06,
            0x04,	0x06,	0x01,	0x06,	0x01,	0x05,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x06,
            0x00,	0x05,	0x01,	0x1E,	0x0F,	0x01,
            0x01,	0x04,	0x05,	0x08,	0x08,	0x01,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
            0x00,	0x00,	0x00,	0x00,	0x00,	0x00,
        ]

        _dev: SPIBus = None
        _initialized: bool = False

        def __init__(self, name: 'Epd17299.SegmentName', pi, left, top, width, height, cs, dc, rst, busy):
            """
            Create a new Segment

            Args:
                name (Epd17299.SegmentName): flag for which segment in the panel this is
                pi (pigpio.pi()): reference to the pigpio engine
                left (integer): leftmost pixel in overall array
                top (integer): topmost pixel in overall array
                width (integer): width of segment in pixels
                height (integer): height of segment in pixels
                cs (integer): GPIO pin for chip select
                dc (integer): GPIO pin for data/command
                rst (integer): GPIO pin for reset
                busy (integer): GPIO pin for busy
            """

            self.name = name
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

            self.reset()

        def _init_display(self):
            if self._initialized:
                return
            self._initialized = True
            with self._dev.transaction(cs=self.cs, dc=self.dc) as tx:
                # configure panel settings
                tx.write(0x00, command=True)
                if self.name == Epd17299.SegmentName.M1 or\
                        self.name == Epd17299.SegmentName.S1:
                    tx.write(0x2f)  # KW-3f   KWR-2F	BWROTP 0f	BWOTP 1f
                else:
                    tx.write(0x23)

                # configure power settings
                if self.name == Epd17299.SegmentName.M1 or\
                        self.name == Epd17299.SegmentName.M2:
                    tx.write(0x01, command=True)
                    tx.write(
                        (
                            0x07,
                            0x17,  # VGH=20V,VGL=-20V
                            0x3F,  # VDH=15V
                            0x3F,  # VDL=-15V
                            0x0D
                        )
                    )

                # configure booster soft-start
                if self.name == Epd17299.SegmentName.M1 or\
                        self.name == Epd17299.SegmentName.M2:
                    tx.write(0x06, command=True)
                    tx.write(
                        (
                            0x17,  # A
                            0x17,  # B
                            0x39,  # C
                            0x17
                        )
                    )

                # configure resolution
                tx.write(0x61, command=True)
                tx.write(struct.pack('>HH', self.width, self.height))

                # DUPSI
                tx.write(0x15, command=True)
                tx.write(0x20)

                # PLL
                tx.write(0x15, command=True)
                tx.write(0x08)

                # Vcom and data interval setting
                tx.write(0x50, command=True)
                tx.write((0x31, 0x07))

                # TCON
                tx.write(0x60, command=True)
                tx.write(0x22)

                # configure power settings
                if self.name == Epd17299.SegmentName.M1 or\
                        self.name == Epd17299.SegmentName.M2:
                    tx.write(0xE0, command=True)
                    tx.write(0x01)

                tx.write(0xE3, command=True)
                tx.write(0x00)

                if self.name == Epd17299.SegmentName.M1 or\
                        self.name == Epd17299.SegmentName.M2:
                    tx.write(0x82, command=True)
                    tx.write(0x1C)

                self.send_lut()

        def __enter__(self):
            self._dev = SPIBus(self.pi, speed=100000,
                               bus=SPIPort.MAIN, busmode=SPIMode.MODE_0)
            self._dev.__enter__()
            self._init_display()

        def __exit__(self, *exc):
            self._dev.__exit__(*exc)

        def reset(self):
            """Reset segment"""
            # TODO: use a nicer pulse than delays; pigpio.wave*(), maybe
            self.pi.write(self.reset, pigpio.HIGH)
            time.sleep(0.2)
            self.pi.write(self.reset, pigpio.LOW)
            time.sleep(0.01)
            self.pi.write(self.reset, pigpio.HIGH)
            time.sleep(0.2)
            logger.debug(f'Reset {self.name}')

        def send_lut(self):
            """Send lookup tables to segment"""
            with self._dev.transaction(cs=self.cs, dc=self.dc) as tx:
                # Vcom
                tx.write(0x20, command=True)
                tx.write(self._lut_vcom1)

                # red not use
                tx.write(0x21, command=True)
                tx.write(self._lut_ww1)

                # bw=r
                tx.write(0x22, command=True)
                tx.write(self._lut_bw1)

                # wb=w
                tx.write(0x23, command=True)
                tx.write(self._lut_wb1)

                # bb=b
                tx.write(0x24, command=True)
                tx.write(self._lut_bb1)

                # bb=b
                tx.write(0x25, command=True)
                tx.write(self._lut_ww1)
            logger.debug(f'Sent LUT to {self.name}')

        def wait_on_busy(self):
            """Wait for the segment not to be busy"""
            logger.debug(f'Waiting for {self.name} not busy...')
            while True:
                with self._dev.transaction(cs=self.cs, dc=self.dc) as tx:
                    tx.write(0x71, command=True)
                    if self.pi.read(self.busy) == 0:
                        break
                    else:
                        continue  # TODO: make a nicer wait instead of spinlock; pigpio.wait_for_edge(), maybe
            logger.debug(f'{self.name} no longer busy!')

        def turn_on(self):
            """Turn the segment on"""
            with self._dev.transaction(cs=self.cs, dc=self.dc) as tx:
                if self.name == Epd17299.SegmentName.M1 or\
                        self.name == Epd17299.SegmentName.M2:
                    tx.write(0x04, command=True)
                time.sleep(0.3)  # TODO: why do we need this delay?
                tx.write(0x12, command=True)
            self.wait_on_busy()
            logger.debug(f'Turned on {self.name}')

        def sleep(self):
            """Sleep the display"""
            with self._dev.transaction(cs=self.cs, dc=self.dc) as tx:
                tx.write(0x02, command=True)
                time.sleep(0.3)  # TODO: why do we need this delay?
                tx.write(0x07, command=True)
                tx.write(0xA5)
                time.sleep(0.3)  # TODO: why do we need this delay?
                self.pi.write(self.reset, pigpio.LOW)
                self.pi.write(self.dc, pigpio.LOW)
                self.pi.write(self.cs, pigpio.HIGH)
            logger.debug(f'Set {self.name} sleep')

        def clear(self):
            """Clear segment"""
            with self._dev.transaction(cs=self.cs, dc=self.dc) as tx:
                tx.write(0x10, command=True)
                tx.write(b'\xFF'*(self.width*self.height))

                tx.write(0x13, command=True)
                tx.write(b'\x00'*(self.width*self.height))
            logger.debug(f'Cleared {self.name}')

        def display(self,image: Image):

            # use the RED channel as the red image
            #  but convert it to 1-bit as the display draws "black" on white
            #  and rotate it to match display orientation
            redimage = self.canvas.getchannel(
                channel='R').convert(mode='1', dither=Image.NONE).rotate(180)

            # use the BLUE channel as the black image
            #  but convert it to 1-bit as the display draws "black" on white
            #  and rotate it to match display orientation
            blackimage = self.canvas.getchannel(
                channel='B').convert(mode='1', dither=Image.NONE).rotate(180)

    def __init__(self):
        self.pi = pigpio.pi()

        # Main SPI pins
        SCK_PIN = 11
        SDO_PIN = 10  # Per https://www.oshwa.org/a-resolution-to-redefine-spi-signal-names/

        self.S2 = Epd17299.Segment(Epd17299.SegmentName.S2, self.pi, left=0, top=0, width=648,
                                   height=492, cs=18, dc=22, rst=23, busy=24)
        self.M1 = Epd17299.Segment(Epd17299.SegmentName.M1, self.pi, left=0, top=492, width=648,
                                   height=492, cs=8, dc=13, rst=6, busy=5)
        self.S1 = Epd17299.Segment(Epd17299.SegmentName.S1, self.pi, left=648, top=0, width=656,
                                   height=492, cs=7, dc=13, rst=6, busy=19)
        self.M2 = Epd17299.Segment(Epd17299.SegmentName.M2, self.pi, left=648, top=492, width=656,
                                   height=492, cs=17, dc=22, rst=23, busy=27)

    def __del__(self):
        self.pi.stop()

    def __enter__(self):
        self._context_stack = contextlib.ExitStack()
        self._context_stack.__enter__()
        self._context_stack.enter_context(self.S2)
        self._context_stack.enter_context(self.M1)
        self._context_stack.enter_context(self.S1)
        self._context_stack.enter_context(self.M2)

    def __exit__(self, *exc):
        self._context_stack.__exit__(*exc)

    def clear(self):
        """Clear the display"""

        logger.debug('Clearing display...')
        self.M1.clear()
        self.M2.clear()
        self.S1.clear()
        self.S2.clear()
        self.turn_on_display()
        logger.debug('Display cleared')

    def sleep(self):
        """Sleep the display"""

        logger.debug('Sleeping display...')
        self.M1.sleep()
        self.M2.sleep()
        self.S1.sleep()
        self.S2.sleep()
        logger.debug('Display is sleeping')

    def turn_on_display(self):
        """Turn on the display"""

        logger.debug('Turning on display...')
        self.M1.turn_on()
        self.M2.turn_on()
        self.S1.turn_on()
        self.S2.turn_on()
        logger.debug('Display is on')

    def display(self):
        pass