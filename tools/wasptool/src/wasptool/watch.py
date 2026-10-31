# SPDX-License-Identifier: LGPL-3.0-or-later
"""What wasptool does on the watch, as Python run through the raw REPL."""

import ast
import asyncio
import base64
import datetime
import time


# Files move in pieces of this many bytes; each piece is one exec, so
# bigger is faster, but the watch must hold the code for a piece in RAM
PIECE = 384

INFO = '''
def _info():
    import gc, os, wasp
    try:
        from version import VERSION as v
    except ImportError:
        v = None
    try:
        s = os.statvfs('/flash')
        f = s[0] * s[4]
    except OSError:
        f = None
    w = wasp.watch
    u = os.uname()
    gc.collect()
    print(repr({
        'version': v,
        'board': u.machine,
        'micropython': u.release,
        'battery': w.battery.level(),
        'charging': w.battery.charging(),
        'voltage_mv': w.battery.voltage_mv(),
        'uptime': w.rtc.uptime,
        'time': w.rtc.get_localtime(),
        'ram_free': gc.mem_free(),
        'flash_free': f,
    }))
_info()
del _info
'''

BINASCII = '''
try:
    import binascii
except ImportError:
    import ubinascii as binascii
'''


async def info(repl):
    """Facts about the watch, as a dict."""
    facts = ast.literal_eval(await repl.exec(INFO))
    facts['charging'] = bool(facts['charging'])
    t = facts.pop('time')
    facts['time'] = datetime.datetime(*t[:6]).isoformat()
    return facts


async def set_time(repl):
    """Set the watch to the local time of this computer."""
    # The watch only takes whole seconds. Time a round trip, then send the
    # next second so that it arrives as that second starts.
    start = time.monotonic()
    await repl.exec('import wasp')
    delay = (time.monotonic() - start) / 2
    target = int(time.time() + delay) + 1
    await asyncio.sleep(max(0, target - delay - time.time()))
    await repl.exec('wasp.watch.rtc.set_localtime({!r})'
                    .format(tuple(time.localtime(target)[:8])))


async def time_drift(repl):
    """Seconds the watch is ahead of this computer (negative: behind)."""
    before = time.time()
    t = ast.literal_eval(await repl.exec(
            'import wasp\nprint(wasp.watch.rtc.get_localtime())'))
    host = (before + time.time()) / 2
    # The watch reports whole seconds: on average it is half a second on
    watch = datetime.datetime(*t[:6]).timestamp() + 0.5
    return round(watch - host)


def chunks(source):
    """Split a Python file into pieces the watch can compile one by one.

    The watch compiles all the code it gets at once, and a whole app may
    not fit in its RAM. Each top-level class starts a new piece, so apps
    can mark more places to split with an empty class.
    """
    pieces = [[]]
    for line in source.splitlines(keepends=True):
        if line.startswith('class ') and any(l.strip() for l in pieces[-1]):
            pieces.append([])
        pieces[-1].append(line)
    return [''.join(p) for p in pieces]


async def notify(repl, title, body, id=1):
    """Show a notification on the watch and buzz."""
    msg = {'title': title, 'body': body}
    await repl.exec(f'import wasp\nwasp.system.notify({int(id)}, {msg!r})\n'
                    'wasp.watch.vibrator.pulse(ms=wasp.system.notify_duration)')


async def _mkdirs(repl, path):
    parts = path.split('/')[:-1]
    for i in range(1, len(parts) + 1):
        d = '/'.join(parts[:i])
        if d:
            await repl.exec(f'import os\ntry:\n os.mkdir({d!r})\n'
                            'except OSError:\n pass')


async def push(repl, data, remote, progress=None):
    """Write data (bytes) to a file on the watch."""
    await _mkdirs(repl, remote)
    await repl.exec(BINASCII + f'_f = open({remote!r}, "wb")')
    try:
        for i in range(0, len(data), PIECE):
            b64 = base64.b64encode(data[i:i + PIECE])
            await repl.exec(f'_f.write(binascii.a2b_base64({b64!r}))')
            if progress:
                progress(min(i + PIECE, len(data)), len(data))
    finally:
        await repl.exec('_f.close()\ndel _f')
    if progress and not data:
        progress(0, 0)


async def pull(repl, remote, progress=None):
    """Read a file from the watch, as bytes."""
    size = int(await repl.exec(f'import os\nprint(os.stat({remote!r})[6])'))
    await repl.exec(BINASCII + f'_f = open({remote!r}, "rb")')
    data = bytearray()
    try:
        while True:
            b64 = await repl.exec('print(binascii.b2a_base64'
                                  f'(_f.read({PIECE})).decode().strip())')
            if not b64.strip():
                break
            data += base64.b64decode(b64)
            if progress:
                progress(len(data), size)
    finally:
        await repl.exec('_f.close()\ndel _f')
    return bytes(data)


async def resume(repl):
    """Make sure the watch runs again, and leave the raw REPL.

    On a watch, wasp.system.run() returns at once if the system is still
    running in the background. If it is not (it was stopped), run() takes
    over the REPL: that is fine, we disconnect and it carries on.
    """
    await repl.start('import wasp\nwasp.system.run()')
    out = await repl.stream.read_until(b'\n', timeout=5)
    if b'already running' in out:
        await repl.stream.read_until(b'>', timeout=5)
        await repl.leave()


async def reset(repl, bootloader=False):
    """Reboot the watch, into the bootloader for an update if asked."""
    if bootloader:
        # Firmware built on the wasp-os fork of MicroPython has
        # machine.enter_ota_dfu(); on upstream MicroPython it is
        # the standard machine.bootloader()
        call = ("getattr(machine, 'enter_ota_dfu', "
                "getattr(machine, 'bootloader', None))()")
    else:
        call = 'machine.reset()'
    await repl.start('import machine\n' + call)
