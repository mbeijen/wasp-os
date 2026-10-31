# SPDX-License-Identifier: LGPL-3.0-or-later
"""A stand-in for a watch's console that speaks MicroPython's raw REPL.

It runs the code it gets in this Python, and fails a test if the host
ever sends more than the watch's 128 byte receive buffer can hold.
"""

import asyncio
import contextlib
import io
import traceback

from wasptool.ble import Stream

BANNER = b'raw REPL; CTRL-B to exit\r\n>'
RING = 128


class Overflow(AssertionError):
    pass


class FakeWatch(Stream):
    def __init__(self, paste=True, window=RING):
        super().__init__()
        self.paste = paste          # False: firmware without raw-paste
        self.window = window
        self.mode = 'friendly'
        self.code = bytearray()
        self.unacked = 0
        self.namespace = {}
        self.writes = []

    @property
    def address(self):
        return 'DD:ED:1A:F1:F1:7A'

    @property
    def name(self):
        return 'mpus'

    async def write(self, data, response=True):
        self.writes.append((bytes(data), response))
        for b in data:
            self._byte(bytes([b]))

    def _run(self, prefix):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                exec(self.code.decode(), self.namespace)
            except Exception:
                err.write(traceback.format_exc())
        self.code.clear()
        self.feed(prefix + out.getvalue().encode() + b'\x04'
                  + err.getvalue().encode() + b'\x04>')

    def _byte(self, b):
        if self.mode == 'friendly':
            if b == b'\x01':
                self.mode = 'raw'
                self.feed(BANNER)
            elif b == b'\x03':
                self.feed(b'\r\n>>> ')
        elif self.mode == 'raw':
            if b == b'\x01':
                self.code.clear()
                self.feed(BANNER)
            elif b == b'\x02':
                self.mode = 'friendly'
                self.feed(b'\r\n>>> ')
            elif b == b'\x04':
                self._run(b'OK')
            elif b == b'\x05' and self.paste:
                self.mode = 'paste-request'
            else:
                self.code += b
        elif self.mode == 'paste-request':
            if b == b'A':
                self.mode = 'paste-request-A'
        elif self.mode == 'paste-request-A':
            self.mode = 'paste'
            self.unacked = 0
            self.feed(b'R\x01' + self.window.to_bytes(2, 'little') + b'\x01')
        elif self.mode == 'paste':
            if b == b'\x04':
                self.mode = 'raw'
                self.feed(b'\x04')
                self._run(b'')
                return
            self.code += b
            self.unacked += 1
            if self.unacked > RING:
                raise Overflow(f'{self.unacked} bytes sent before the watch '
                               f'could take them')
            if self.unacked == self.window:
                # The watch takes a window's worth from its buffer, but
                # not before the host has had a chance to send more
                asyncio.get_running_loop().call_soon(self._ack)

    def _ack(self):
        self.unacked -= self.window
        self.feed(b'\x01')
