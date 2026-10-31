# SPDX-License-Identifier: LGPL-3.0-or-later
"""Find a wasp-os watch and talk to its console over Bluetooth.

The console is the Nordic UART Service (NUS): the host writes to one
characteristic and the watch notifies on another. Both the old wasp-os
firmware and upstream MicroPython send and accept at most 20 bytes at a
time, and the watch keeps only 128 received bytes, so anything bigger
than a line needs flow control on top (see :mod:`wasptool.repl`).
"""

import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

NUS_SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NUS_RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'    # host to watch
NUS_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'    # watch to host
CHUNK = 20
# The name upstream MicroPython gives its console. BlueZ does not always
# pass on the service UUIDs it advertises (it can drop them after a
# connection), so the name is the fallback.
NAMES = ('mpus',)

log = logging.getLogger(__name__)


class NotFound(Exception):
    pass


class Stream:
    """Bytes from the watch, buffered until a reader asks for them."""

    def __init__(self):
        self._buf = bytearray()
        self._more = asyncio.Event()
        self.echo = None
        self.connected = True

    def feed(self, data):
        if self.echo:
            self.echo(bytes(data))
        self._buf += data
        self._more.set()

    async def _wait(self, deadline):
        if not self.connected:
            raise ConnectionError('The watch disconnected')
        timeout = deadline - asyncio.get_running_loop().time()
        if timeout <= 0:
            raise TimeoutError()
        self._more.clear()
        await asyncio.wait_for(self._more.wait(), timeout)

    async def read_until(self, marker, timeout=10.0):
        """Return everything up to marker, and drop the marker itself."""
        deadline = asyncio.get_running_loop().time() + timeout
        while (i := self._buf.find(marker)) < 0:
            try:
                await self._wait(deadline)
            except TimeoutError:
                raise TimeoutError(f'Timed out waiting for {marker!r}, '
                                   f'got {bytes(self._buf[-80:])!r}') from None
        data = bytes(self._buf[:i])
        del self._buf[:i + len(marker)]
        return data

    async def read(self, n, timeout=10.0):
        """Return exactly n bytes."""
        deadline = asyncio.get_running_loop().time() + timeout
        while len(self._buf) < n:
            await self._wait(deadline)
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    def pending(self):
        return len(self._buf)

    async def settle(self, quiet=0.3, timeout=3.0):
        """Wait until the watch has stopped sending.

        Hanging up while the watch is still sending output hangs the
        watch: upstream MicroPython's nRF port then waits forever for
        notifications to complete, and the watchdog resets it into the
        bootloader. So let it finish first.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self.connected and loop.time() < deadline:
            self._more.clear()
            try:
                await asyncio.wait_for(self._more.wait(), quiet)
            except TimeoutError:
                return

    def discard(self):
        self._buf.clear()

    async def write(self, data, response=True):
        raise NotImplementedError


def _is_address(target):
    # A MAC address (Linux, Windows) or a CoreBluetooth UUID (macOS)
    return target.count(':') == 5 or target.count('-') == 4


def matches(device, adv, target=None):
    """True if the advertisement is a wasp-os console we are looking for."""
    if target:
        if _is_address(target):
            return device.address.upper() == target.upper()
        return target in (device.name, adv.local_name)
    return NUS_SERVICE in adv.service_uuids or adv.local_name in NAMES


async def find(target=None, timeout=10.0):
    """Scan for a watch: by name or address, or else any wasp-os watch."""
    device = await BleakScanner.find_device_by_filter(
            lambda d, a: matches(d, a, target), timeout=timeout)
    if device is None:
        what = target or 'a wasp-os watch'
        raise NotFound(f'Cannot find {what}: is it awake, and not '
                       'connected to a phone or another computer?')
    return device


async def scan(timeout=5.0):
    """List the watches in range, as (device, advertisement) pairs."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    return [(d, a) for d, a in found.values() if matches(d, a)]


class Console(Stream):
    """A connection to the console of a watch."""

    def __init__(self, device):
        super().__init__()
        self.device = device
        self._client = BleakClient(device, disconnected_callback=self._lost)
        self.connected = False
        self.on_lost = None

    def _lost(self, client):
        self.connected = False
        self._more.set()
        if self.on_lost:
            self.on_lost()

    @property
    def address(self):
        return self.device.address

    @property
    def name(self):
        return self.device.name

    async def open(self, timeout=10.0):
        await self._client.connect(timeout=timeout)
        self.connected = True
        await self._client.start_notify(NUS_TX, lambda c, d: self.feed(d))

    async def close(self):
        if self._client.is_connected:
            await self.settle()
            await self._client.disconnect()
        self.connected = False

    async def write(self, data, response=True):
        """Write in 20 byte pieces.

        With response, each piece waits until the watch has it, which paces
        the writes. Without, they go out as fast as the link allows: only use
        that when something else stops the watch's buffer overflowing.
        """
        if not self.connected:
            raise ConnectionError('The watch disconnected')
        for i in range(0, len(data), CHUNK):
            await self._client.write_gatt_char(NUS_RX, data[i:i + CHUNK],
                                               response=response)


async def connect(target=None, retries=3, timeout=10.0):
    """Find a watch and connect to its console, retrying on failure.

    The first connection attempt fails now and again, more so on radios
    that share their antenna with Wi-Fi. Each attempt scans again, since
    BlueZ forgets devices it has not seen for a while.
    """
    for attempt in range(1, retries + 1):
        device = await find(target, timeout)
        console = Console(device)
        try:
            log.debug('Connecting to %s (%s)', device.name, device.address)
            await console.open(timeout)
            return console
        except (BleakError, TimeoutError, OSError) as e:
            await console.close()
            if attempt == retries:
                raise ConnectionError(f'Cannot connect to {device.address} '
                                      f'after {retries} attempts: {e}') from e
            log.warning('Connecting failed (%s), retrying', e or type(e).__name__)
            await asyncio.sleep(1)
