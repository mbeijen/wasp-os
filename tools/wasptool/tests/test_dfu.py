# SPDX-License-Identifier: LGPL-3.0-or-later

import asyncio
import json
import zipfile

import pytest

from wasptool import dfu


def test_next_address():
    assert dfu.next_address('DD:ED:1A:F1:F1:7A') == 'DD:ED:1A:F1:F1:7B'
    assert dfu.next_address('dd:ed:1a:f1:f1:ff') == 'DD:ED:1A:F1:F2:00'


def test_read_package(tmp_path):
    path = tmp_path / 'micropython.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('manifest.json', json.dumps({'manifest': {'application': {
            'bin_file': 'firmware.bin', 'dat_file': 'firmware.dat'}}}))
        z.writestr('firmware.bin', b'image')
        z.writestr('firmware.dat', b'init')
    assert dfu.read_package(path) == (b'image', b'init')


class FakeBootloader:
    """Answers the way the legacy bootloader does."""

    def __init__(self, updater, fail_validation=False):
        self.updater = updater
        self.fail_validation = fail_validation
        self.image = bytearray()
        self.packets = 0
        self.receiving = False

    def note(self, *data):
        self.updater._notes.put_nowait(bytes(data))

    async def write_gatt_char(self, char, data, response):
        if char == dfu.CONTROL:
            op = data[0]
            if op == dfu.START_DFU:
                self.note(dfu.RESPONSE, op, 1)
            elif op == dfu.INITIALIZE_DFU and data[1] == 1:
                self.note(dfu.RESPONSE, op, 1)
            elif op == dfu.PRN_REQUEST:
                self.interval = int.from_bytes(data[1:3], 'little')
            elif op == dfu.RECEIVE_FIRMWARE_IMAGE:
                self.receiving = True
            elif op == dfu.VALIDATE_FIRMWARE:
                self.note(dfu.RESPONSE, op, 6 if self.fail_validation else 1)
        elif self.receiving:
            self.image += data
            self.packets += 1
            if self.packets % self.interval == 0:
                self.note(dfu.PACKET_RECEIPT,
                          *len(self.image).to_bytes(4, 'little'))
            if len(self.image) == self.size:
                self.note(dfu.RESPONSE, dfu.RECEIVE_FIRMWARE_IMAGE, 1)
        elif len(data) == 12:
            self.size = int.from_bytes(data[8:], 'little')


# 400 bytes is exactly 20 packets, so a receipt comes before the response
@pytest.mark.parametrize('size', (1000, 400, 7))
def test_update(size):
    image = bytes(i % 251 for i in range(size))

    async def go():
        up = dfu.Updater(None, image, b'init')
        up._client = fake = FakeBootloader(up)
        await up.run()
        return fake
    assert asyncio.run(go()).image == image


def test_update_failure():
    async def go():
        up = dfu.Updater(None, b'x' * 100, b'init')
        up._client = FakeBootloader(up, fail_validation=True)
        await up.run()
    with pytest.raises(dfu.DfuError, match='operation failed'):
        asyncio.run(go())
