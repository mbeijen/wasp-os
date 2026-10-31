# SPDX-License-Identifier: LGPL-3.0-or-later
"""An interactive MicroPython prompt on the watch."""

import asyncio
import os
import sys
import threading

EXIT = b'\x18'      # Ctrl-X


def _keys_posix(put):
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)

    def reader():
        while True:
            data = os.read(fd, 64)
            put(data)
            if not data or EXIT in data:
                return

    threading.Thread(target=reader, daemon=True).start()
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _keys_windows(put):
    import msvcrt

    def reader():
        while True:
            data = msvcrt.getwch().encode()
            put(data)
            if EXIT in data:
                return

    threading.Thread(target=reader, daemon=True).start()
    return lambda: None


async def interact(console):
    """Pass keys to the watch and its output to the terminal until Ctrl-X."""
    loop = asyncio.get_running_loop()
    keys = asyncio.Queue()
    out = sys.stdout.buffer

    def show(data):
        out.write(data)
        out.flush()

    # Show the output as it comes rather than buffering it for a reader
    console.feed = show
    put = lambda data: loop.call_soon_threadsafe(keys.put_nowait, data)
    restore = (_keys_windows if os.name == 'nt' else _keys_posix)(put)
    lost = loop.create_future()
    console.on_lost = lambda: lost.done() or lost.set_result(None)
    try:
        # Leave the raw REPL, if someone left it there, and ask for a prompt
        await console.write(b'\x02\r')
        while True:
            key = asyncio.ensure_future(keys.get())
            await asyncio.wait((key, lost), return_when=asyncio.FIRST_COMPLETED)
            if not key.done():
                key.cancel()
                print('\r\nThe watch disconnected', end='')
                break
            data = key.result()
            if not data or EXIT in data:
                break
            await console.write(data.replace(b'\n', b'\r'))
    finally:
        restore()
        print()
