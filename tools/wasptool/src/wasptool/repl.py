# SPDX-License-Identifier: LGPL-3.0-or-later
"""Run Python on the watch through MicroPython's raw REPL.

The raw REPL does not echo what it is sent and frames the output, so
there is no need to scrape prompts. Raw-paste mode (MicroPython 1.14 and
later) adds flow control: the watch says how many bytes it can take and
sends ``\\x01`` each time it has consumed that many. Older firmware gets
the code in paced writes instead.
"""

import asyncio

RAW_BANNER = b'raw REPL; CTRL-B to exit\r\n>'


class ReplError(Exception):
    """The code raised an exception on the watch."""

    def __init__(self, traceback):
        super().__init__(traceback.strip().splitlines()[-1])
        self.traceback = traceback


class Repl:
    def __init__(self, stream):
        self.stream = stream
        self._paste = True

    async def enter(self):
        """Enter the raw REPL.

        On a watch the system runs in the background, so the REPL is
        normally idle and takes Ctrl-A straight away. Only if it does not
        answer is something running in the foreground, and do we interrupt
        it with Ctrl-C. Interrupting is best avoided: upstream MicroPython's
        nRF port can raise the KeyboardInterrupt inside the RTC interrupt
        that feeds the watchdog, which then resets the watch into its
        bootloader.
        """
        s = self.stream
        s.discard()
        await s.write(b'\x01')
        try:
            await s.read_until(RAW_BANNER, timeout=2)
            return
        except TimeoutError:
            pass
        await s.write(b'\r\x03\x03')
        await asyncio.sleep(0.2)
        s.discard()
        await s.write(b'\x01')
        await s.read_until(RAW_BANNER)

    async def leave(self):
        """Return to the normal REPL, and wait for its prompt."""
        await self.stream.write(b'\x02')
        await self.stream.read_until(b'>>> ', timeout=5)

    async def _paste_mode(self, code):
        """Send code in raw-paste mode; False if the watch lacks it."""
        s = self.stream
        await s.write(b'\x05A\x01')
        reply = await s.read(2)
        if reply == b'R\x00':
            return False
        if reply != b'R\x01':
            # Old firmware took the \x01 as a request to re-enter the raw
            # REPL, and printed its banner (the "ra" of which we just read)
            await s.read_until(RAW_BANNER[2:])
            return False

        window = int.from_bytes(await s.read(2), 'little')
        # The watch offers two windows, but upstream MicroPython's console
        # only buffers 128 bytes: use one, so it can never overflow
        await s.read(1)
        credit = window
        i = 0
        ended = False
        while i < len(code) and not ended:
            while credit == 0 or s.pending():
                flag = await s.read(1)
                if flag == b'\x01':
                    credit += window
                elif flag == b'\x04':
                    # The watch hit a syntax error and wants no more
                    ended = True
                    break
                else:
                    raise IOError(f'Unexpected {flag!r} in raw-paste mode')
            if not ended:
                piece = code[i:i + credit]
                await s.write(piece, response=False)
                credit -= len(piece)
                i += len(piece)
        await s.write(b'\x04')
        if not ended:
            await s.read_until(b'\x04')
        return True

    async def _send(self, code):
        if self._paste:
            if await self._paste_mode(code):
                return
            self._paste = False
        # Writes with response, one piece at a time: slow but safe
        await self.stream.write(code + b'\x04')
        reply = await self.stream.read(2)
        if reply != b'OK':
            raise IOError(f'Unexpected reply {reply!r} from the raw REPL')

    async def exec(self, code, timeout=10.0):
        """Run code on the watch and return what it prints.

        Raises ReplError, with the traceback, if the code raises.
        """
        if isinstance(code, str):
            code = code.encode()
        await self._send(code)
        out = await self.stream.read_until(b'\x04', timeout)
        err = await self.stream.read_until(b'\x04', timeout)
        await self.stream.read_until(b'>', timeout)
        if err:
            raise ReplError(err.decode(errors='replace'))
        return out.decode(errors='replace')

    async def start(self, code):
        """Run code without waiting for it to finish (to reset, say)."""
        if isinstance(code, str):
            code = code.encode()
        await self._send(code)
