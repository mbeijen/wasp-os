# SPDX-License-Identifier: LGPL-3.0-or-later AND Apache-2.0
"""Firmware updates over Bluetooth, with Nordic's legacy DFU protocol.

This is the protocol the PineTime bootloader speaks. Based on
tools/ota-dfu in wasp-os, which comes from foldedtoad's Python nRF5 OTA
DFU controller (Apache-2.0).
"""

import asyncio
import json
import logging
import zipfile

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

DFU_SERVICE = '00001530-1212-efde-1523-785feabcd123'
CONTROL = '00001531-1212-efde-1523-785feabcd123'
PACKET = '00001532-1212-efde-1523-785feabcd123'

START_DFU = 1
INITIALIZE_DFU = 2
RECEIVE_FIRMWARE_IMAGE = 3
VALIDATE_FIRMWARE = 4
ACTIVATE_IMAGE_AND_RESET = 5
PRN_REQUEST = 8
RESPONSE = 16
PACKET_RECEIPT = 17

RESULTS = {1: 'success', 2: 'invalid state', 3: 'not supported',
           4: 'data size exceeds limits', 5: 'CRC error',
           6: 'operation failed'}

APPLICATION = 4
PIECE = 20
# A packet receipt every 20 packets: measured on a PineTime, going from 5
# to 20 cut a full update by about a third
RECEIPT_INTERVAL = 20

log = logging.getLogger(__name__)


class DfuError(Exception):
    pass


def read_package(path):
    """The application image and init packet from a DFU zip."""
    with zipfile.ZipFile(path) as z:
        try:
            app = json.loads(z.read('manifest.json'))['manifest']['application']
            bin_name, dat_name = app['bin_file'], app['dat_file']
        except KeyError:
            names = z.namelist()
            bin_name = next(n for n in names if n.endswith('.bin'))
            dat_name = next(n for n in names if n.endswith('.dat'))
        return z.read(bin_name), z.read(dat_name)


def next_address(address):
    """The bootloader advertises at the watch's address plus one."""
    n = int(address.replace(':', ''), 16) + 1
    return ':'.join(f'{(n >> s) & 0xff:02X}' for s in range(40, -1, -8))


async def find(address=None, timeout=15.0):
    """Scan for a watch in its bootloader.

    Given the address the watch has when running wasp-os, look for that
    address plus one (or the same address, in case the bootloader keeps
    it). Otherwise, or on macOS, which hides addresses, look for any device
    offering the DFU service.
    """
    wanted = set()
    if address and address.count(':') == 5:
        wanted = {address.upper(), next_address(address)}

    def match(d, a):
        if wanted:
            return d.address.upper() in wanted
        return DFU_SERVICE in a.service_uuids

    device = await BleakScanner.find_device_by_filter(match, timeout=timeout)
    if device is None:
        raise DfuError('Cannot find a watch in its bootloader')
    return device


class Updater:
    def __init__(self, device, image, init, progress=None):
        self.device = device
        self.image = image
        self.init = init
        self.progress = progress
        self._client = None
        self._notes = asyncio.Queue()

    async def connect(self, retries=3, timeout=10.0):
        for attempt in range(1, retries + 1):
            self._client = BleakClient(self.device)
            try:
                await self._client.connect(timeout=timeout)
                await self._client.start_notify(
                        CONTROL, lambda c, d: self._notes.put_nowait(bytes(d)))
                return
            except (BleakError, TimeoutError, OSError) as e:
                await self.close()
                if attempt == retries:
                    raise
                log.warning('Connecting to the bootloader failed (%s), '
                            'retrying', e or type(e).__name__)
                await asyncio.sleep(1)

    async def close(self):
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    async def _command(self, *args):
        await self._client.write_gatt_char(CONTROL, bytes(args), response=True)

    async def _data(self, data):
        # Flow control comes from the packet receipts, so no responses
        await self._client.write_gatt_char(PACKET, data, response=False)

    async def _note(self, timeout=10.0):
        try:
            return await asyncio.wait_for(self._notes.get(), timeout)
        except TimeoutError:
            raise DfuError('The bootloader stopped answering') from None

    async def _expect(self, procedure, timeout=10.0):
        note = await self._note(timeout)
        # When the image ends on a receipt interval, a last packet receipt
        # may come before the response
        while note[0] == PACKET_RECEIPT:
            note = await self._note(timeout)
        if len(note) < 3 or note[0] != RESPONSE or note[1] != procedure:
            raise DfuError(f'Unexpected reply {note.hex()} from the bootloader')
        if note[2] != 1:
            raise DfuError(f'The bootloader reported '
                           f'{RESULTS.get(note[2], note[2])} (step {procedure})')

    async def run(self):
        image = self.image
        await self._command(START_DFU, APPLICATION)
        # The sizes of the SoftDevice, bootloader and application
        await self._data(bytes(8) + len(image).to_bytes(4, 'little'))
        await self._expect(START_DFU)

        await self._command(INITIALIZE_DFU, 0)
        await self._data(self.init)
        await self._command(INITIALIZE_DFU, 1)
        await self._expect(INITIALIZE_DFU)

        await self._command(PRN_REQUEST, *RECEIPT_INTERVAL.to_bytes(2, 'little'))
        await self._command(RECEIVE_FIRMWARE_IMAGE)

        sent = 0
        for n, i in enumerate(range(0, len(image), PIECE), 1):
            await self._data(image[i:i + PIECE])
            sent = min(i + PIECE, len(image))
            if sent < len(image) and n % RECEIPT_INTERVAL == 0:
                note = await self._note()
                if note[0] == RESPONSE:
                    # The bootloader gave up (or was still busy with an
                    # earlier, interrupted transfer)
                    raise DfuError('The bootloader reported '
                                   f'{RESULTS.get(note[2], note[2])} '
                                   'during the upload')
                if note[0] != PACKET_RECEIPT:
                    raise DfuError(f'Unexpected reply {note.hex()}')
                if self.progress:
                    self.progress(int.from_bytes(note[1:5], 'little'),
                                  len(image))
        if self.progress:
            self.progress(sent, len(image))
        await self._expect(RECEIVE_FIRMWARE_IMAGE, timeout=30)

        await self._command(VALIDATE_FIRMWARE)
        await self._expect(VALIDATE_FIRMWARE, timeout=30)

        # Give the bootloader a moment to finish copying
        await asyncio.sleep(1)
        try:
            await self._command(ACTIVATE_IMAGE_AND_RESET)
        except (BleakError, OSError):
            # It may reset before it acknowledges
            pass
