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

# Sent as several small pieces: the heap on a watch that has been running
# for a while is fragmented, and compiling it as one piece needs a larger
# free block than may be left
INFO = (
    'import gc, os, wasp\ngc.collect()',
    "_i = {'board': os.uname().machine, 'micropython': os.uname().release}",
    'try:\n'
    '    from version import VERSION\n'
    "    _i['version'] = VERSION\n"
    'except ImportError:\n'
    "    _i['version'] = None",
    'try:\n'
    "    _i['flash_free'] = os.statvfs('/flash')[0] * os.statvfs('/flash')[4]\n"
    'except OSError:\n'
    "    _i['flash_free'] = None",
    "_i['battery'] = wasp.watch.battery.level()\n"
    "_i['charging'] = wasp.watch.battery.charging()\n"
    "_i['voltage_mv'] = wasp.watch.battery.voltage_mv()",
    "_i['uptime'] = wasp.watch.rtc.uptime\n"
    "_i['time'] = wasp.watch.rtc.get_localtime()",
    # Where the watch hung before its last watchdog reset (newer firmware)
    "_i['last_hang'] = getattr(wasp.watch, 'last_hang', None)",
    "gc.collect()\n_i['ram_free'] = gc.mem_free()\nprint(repr(_i))\ndel _i",
)

BINASCII = '''
try:
    import binascii
except ImportError:
    import ubinascii as binascii
'''


async def info(repl):
    """Facts about the watch, as a dict."""
    for piece in INFO[:-1]:
        await repl.exec(piece)
    facts = ast.literal_eval(await repl.exec(INFO[-1]))
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


class NotAvailable(Exception):
    """The watch does not have what was asked for."""


# The Alarm app, when it is enabled (in the Software app)
ALARM_APP = ("import wasp\n_a = [a for a in wasp.system.launcher_ring "
             "if type(a).__name__ == 'AlarmApp']\n"
             "_a = _a[0] if _a and hasattr(_a[0], 'get_alarms') else None")


async def _alarm_app(repl):
    await repl.exec(ALARM_APP)
    if (await repl.exec('print(_a is not None)')).strip() != 'True':
        raise NotAvailable('the Alarm app is not enabled (see the Software '
                           'app), or this firmware is too old to set alarms')


async def alarms(repl):
    """The alarms, as a list of (hour, minute, days) tuples.

    days is a bit mask: Monday is bit 0, Sunday bit 6, with none for an
    alarm that goes off once, and 0x80 is set if the alarm is on.
    """
    await _alarm_app(repl)
    return ast.literal_eval(await repl.exec('print(_a.get_alarms())\ndel _a'))


async def set_alarms(repl, alarms):
    """Replace the alarms on the watch (up to four)."""
    await _alarm_app(repl)
    await repl.exec(f'_a.set_alarms({[tuple(a) for a in alarms]!r})\ndel _a')


async def faces(repl):
    """The watch faces to choose from, and the one in use, by label."""
    return ast.literal_eval(await repl.exec(
            'import wasp, appregistry\n'
            'print(([f[1] for f in appregistry.faces_list], '
            'type(wasp.system.quick_ring[0]).__name__[:-3]))'))


async def set_face(repl, label):
    """Use the watch face with this label (from faces()), and keep it."""
    await repl.exec(
        'import wasp, appregistry\n'
        f'_f = [f for f in appregistry.faces_list if f[1] == {label!r}][0]\n'
        "_f = '{}.{}App'.format(*_f)")
    await repl.exec(
        '_o = wasp.system.quick_ring[0]\n'
        'wasp.system.register(_f, watch_face=True)\n'
        "if hasattr(wasp.system, 'save_settings'):\n"
        '    wasp.system.save_settings(face=_f)\n'
        'if wasp.system.app is _o:\n'
        '    wasp.system.switch(wasp.system.quick_ring[0])\n'
        'del _f, _o')


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
