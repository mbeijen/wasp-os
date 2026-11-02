# SPDX-License-Identifier: LGPL-3.0-or-later
"""The wasptool command."""

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import sys
import time

from bleak.exc import BleakError

from wasptool import __version__, ble, dfu, releases, watch
from wasptool.repl import Repl, ReplError


def progress_bar(label):
    """A progress callback that draws a bar on a terminal, or nothing."""
    if not sys.stderr.isatty():
        return None
    print(label, file=sys.stderr)

    def draw(done, total):
        pct = 100 * done // total if total else 100
        bar = '#' * (pct // 2) + '.' * (50 - pct // 2)
        if total < 1024:
            size = f'{done} of {total} bytes'
        else:
            size = f'{done // 1024} of {total // 1024} KB'
        print(f'\r[{bar}] {pct:3d}% ({size})',
              end='\n' if done >= total else '', file=sys.stderr, flush=True)
    return draw


@contextlib.asynccontextmanager
async def session(args, resume=True):
    """Connect, enter the raw REPL, and set the watch running afterwards."""
    console = await ble.connect(args.device, args.retries, args.timeout)
    if args.verbose:
        console.echo = lambda d: print(f'<<< {d!r}', file=sys.stderr)
    try:
        repl = Repl(console)
        await repl.enter()
        yield repl
        if resume:
            await watch.resume(repl)
    finally:
        await console.close()


def _duration(secs):
    mins, secs = divmod(int(secs), 60)
    hours, mins = divmod(mins, 60)
    days, hours = divmod(hours, 24)
    return (f'{days}d ' if days else '') + f'{hours:02d}:{mins:02d}:{secs:02d}'


async def cmd_scan(args):
    found = await ble.scan(args.timeout)
    for device, adv in sorted(found, key=lambda f: -f[1].rssi):
        print(f'{device.address}  {adv.rssi:4d} dBm  {device.name or ""}')
    if not found:
        print('No wasp-os watches found', file=sys.stderr)
        return 1


async def cmd_info(args):
    async with session(args) as repl:
        facts = await watch.info(repl)
        facts['address'] = repl.stream.address
        facts['name'] = repl.stream.name
    if args.json:
        print(json.dumps(facts, indent=2))
        return

    battery = f"{facts['battery']}% ({facts['voltage_mv'] / 1000:.2f} V)"
    if facts['charging']:
        battery += ', charging'
    flash = facts['flash_free']
    rows = (
        ('Version', facts['version'] or 'unknown (too old to say)'),
        ('Board', facts['board']),
        ('MicroPython', facts['micropython']),
        ('Bootloader', facts.get('bootloader') or '-'),
        ('Address', f"{facts['address']} ({facts['name']})"),
        ('Battery', battery),
        ('Uptime', _duration(facts['uptime'])),
        ('Time', facts['time'].replace('T', ' ')),
        ('RAM free', f"{facts['ram_free'] // 1024} KB"),
        ('Flash free', '-' if flash is None else f'{flash // 1024} KB'),
    )
    hang = facts.get('last_hang')
    if hang:
        pc, lr, xpsr, ms = hang
        if xpsr == 0:
            where = 'a fatal error'
        elif xpsr & 0x1ff == 0:
            where = 'not in an interrupt'
        else:
            where = f'in exception {xpsr & 0x1ff}'
        rows += (('Last hang', f'pc {pc:#x}, lr {lr:#x}, {where}, '
                               f'{ms} ms after the last alive()'),)
    for label, value in rows:
        print(f'{label:<12} {value}')


async def cmd_rtc(args):
    async with session(args) as repl:
        if args.action == 'set':
            await watch.set_time(repl)
        drift = await watch.time_drift(repl)
    if drift == 0:
        print('The watch is on time')
    else:
        side = 'ahead' if drift > 0 else 'behind'
        print(f'The watch is {abs(drift)} s {side}'
              + ('' if args.action == 'set' else ': use "wasptool rtc set"'))


async def cmd_notify(args):
    async with session(args) as repl:
        await watch.notify(repl, args.title, args.body, args.id)


DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
REPEATS = {'once': 0, 'daily': 0x7f, 'weekdays': 0x1f, 'weekends': 0x60}
ALARM_ON = 0x80


def parse_time(text):
    """'7:30' as (7, 30)."""
    try:
        hour, minute = (int(t) for t in text.split(':'))
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not a time like 7:30')
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise argparse.ArgumentTypeError(f'{text!r} is not a time of day')
    return hour, minute


def parse_days(text):
    """'weekdays', or a list like 'mon,wed', as a mask of days."""
    if text.lower() in REPEATS:
        return REPEATS[text.lower()]
    mask = 0
    for day in text.lower().split(','):
        found = [i for i, d in enumerate(DAYS)
                 if len(day) >= 2 and d.lower().startswith(day)]
        if len(found) != 1:
            raise argparse.ArgumentTypeError(
                    f'{day!r} is not a day: use for example mon,wed, '
                    'or one of ' + ', '.join(REPEATS))
        mask |= 1 << found[0]
    return mask


def format_days(mask):
    mask &= 0x7f
    for name, m in REPEATS.items():
        if mask == m:
            return name
    return ','.join(d for i, d in enumerate(DAYS) if mask & (1 << i))


def print_alarms(alarms):
    if not alarms:
        print('No alarms')
    for hour, minute, days in alarms:
        state = 'on' if days & ALARM_ON else 'off'
        print(f'{hour:2d}:{minute:02d}  {state:<3}  {format_days(days)}')


async def cmd_alarm(args):
    async with session(args) as repl:
        alarms = await watch.alarms(repl)
        if args.action == 'set':
            days = args.days | (0 if args.off else ALARM_ON)
            same = [i for i, a in enumerate(alarms) if a[:2] == args.time]
            if same:
                alarms[same[0]] = (*args.time, days)
            elif len(alarms) >= 4:
                print('The watch has room for four alarms: '
                      'unset one first', file=sys.stderr)
                return 1
            else:
                alarms.append((*args.time, days))
        elif args.action == 'unset':
            if args.time == 'all':
                kept = []
            else:
                time = parse_time(args.time)
                kept = [a for a in alarms if a[:2] != time]
                if len(kept) == len(alarms):
                    print(f'There is no alarm at {args.time}', file=sys.stderr)
                    return 1
            alarms = kept
        if args.action != 'list':
            await watch.set_alarms(repl, alarms)
    print_alarms(alarms)


def _face_key(name):
    return name.lower().replace('_', '').replace('-', '').replace(' ', '')


async def cmd_face(args):
    async with session(args) as repl:
        faces, current = await watch.faces(repl)
        if args.name:
            found = [f for f in faces if _face_key(f) == _face_key(args.name)]
            if not found:
                print(f'There is no watch face {args.name!r}: choose from '
                      + ', '.join(faces), file=sys.stderr)
                return 1
            await watch.set_face(repl, found[0])
            current = found[0]
    for face in faces:
        print(('* ' if face == current else '  ') + face)


async def _run(args, chunks):
    async with session(args) as repl:
        for chunk in chunks:
            try:
                out = await repl.exec(chunk, timeout=args.exec_timeout)
            except ReplError as e:
                print(e.traceback, end='', file=sys.stderr)
                return 1
            print(out, end='', flush=True)


async def cmd_eval(args):
    return await _run(args, [args.code])


async def cmd_exec(args):
    with open(args.file) as f:
        return await _run(args, watch.chunks(f.read()))


async def cmd_push(args):
    with open(args.local, 'rb') as f:
        data = f.read()
    remote = args.remote or os.path.basename(args.local)
    async with session(args) as repl:
        await watch.push(repl, data, remote, progress_bar(f'{args.local} -> {remote}'))


async def cmd_pull(args):
    local = args.local or os.path.basename(args.remote)
    if os.path.exists(local) and not args.force:
        print(f'{local} exists: use --force to overwrite it', file=sys.stderr)
        return 1
    async with session(args) as repl:
        data = await watch.pull(repl, args.remote, progress_bar(f'{args.remote} -> {local}'))
    with open(local, 'wb') as f:
        f.write(data)


async def cmd_console(args):
    from wasptool.console import interact
    console = await ble.connect(args.device, args.retries, args.timeout)
    print(f'Connected to {console.name} ({console.address}). '
          'Exit with Ctrl-X.', file=sys.stderr)
    try:
        await interact(console)
    finally:
        await console.close()


async def cmd_reset(args):
    async with session(args, resume=False) as repl:
        await watch.reset(repl, args.bootloader)
        await asyncio.sleep(0.5)


async def cmd_ota(args):
    await _ota(args, args.file)


async def _ota(args, package):
    """Update the firmware from a DFU zip (a path, or a file object)."""
    image, init = dfu.read_package(package)
    address = None
    try:
        async with session(args, resume=False) as repl:
            address = repl.stream.address
            print(f'Rebooting {repl.stream.name} ({address}) into the bootloader',
                  file=sys.stderr)
            await watch.reset(repl, bootloader=True)
            await asyncio.sleep(0.5)
    except ble.NotFound:
        # Perhaps it is in the bootloader already
        print('No watch running wasp-os found, '
              'looking for one in its bootloader', file=sys.stderr)
        if args.device and args.device.count(':') == 5:
            address = args.device
    await asyncio.sleep(2)

    updater = dfu.Updater(address, image, init, progress_bar('Updating'))
    start = time.monotonic()
    await updater.connect(args.retries, args.timeout)
    try:
        await updater.run()
    finally:
        await updater.close()
    secs = int(time.monotonic() - start)
    print(f'Updated in {secs // 60} min {secs % 60} s: the watch is restarting',
          file=sys.stderr)


def _confirm(question):
    if not sys.stdin.isatty():
        raise watch.NotAvailable('not updating without asking: '
                                 'pass --yes to update anyway')
    return input(question + ' [y/N] ').strip().lower() in ('y', 'yes')


async def cmd_update(args):
    manifest = releases.fetch(args.url)
    async with session(args) as repl:
        current = await watch.version(repl)
        name, address = repl.stream.name, repl.stream.address
    target = releases.latest(manifest)
    new = releases.newer(manifest, current)
    print(f'{name} runs {current or "a version too old to say"}; '
          f'the latest build is {target["version"]} ({target["date"]})')
    if not args.force:
        if current == target['version']:
            print('The watch is up to date')
            return
        if not new:
            print('The watch runs a newer build: nothing to update')
            return
    for r in new:
        print(f'\n{r["version"]} ({r["date"]})')
        for line in (r.get('notes') or 'No notes.').splitlines():
            print('  ' + line)
    if args.check:
        return
    print()
    if not args.yes and not _confirm(f'Update to {target["version"]}?'):
        return 1

    data = releases.download(manifest, target)
    print(f'Downloaded {releases.FIRMWARE} ({len(data) // 1024} KB), '
          'its sha256 matches', file=sys.stderr)
    # The watch we just talked to, without scanning again
    args.device = args.device or address
    await _ota(args, io.BytesIO(data))


def parser():
    p = argparse.ArgumentParser(
            prog='wasptool',
            description='Talk to a wasp-os watch over Bluetooth.')
    p.add_argument('--version', action='version', version=f'%(prog)s {__version__}')

    def options(p, default):
        """The options that go before or after the command."""
        p.add_argument('-d', '--device', metavar='NAME|ADDRESS',
                       default=default(None),
                       help='the watch to use (default: the first one found)')
        p.add_argument('--retries', type=int, default=default(3),
                       help='connection attempts before giving up (default: 3)')
        p.add_argument('--timeout', type=float, default=default(10.0),
                       help='seconds to scan, or to connect (default: 10)')
        p.add_argument('-v', '--verbose', action='store_true',
                       default=default(False),
                       help='show what goes on, including the console traffic')

    options(p, lambda d: d)
    # After the command they must not reset what was given before it
    common = argparse.ArgumentParser(add_help=False)
    options(common, lambda d: argparse.SUPPRESS)
    sub = p.add_subparsers(dest='command', required=True, metavar='COMMAND')

    def command(name, func, help):
        c = sub.add_parser(name, help=help, description=help, parents=[common])
        c.set_defaults(func=func)
        return c

    command('scan', cmd_scan, 'list the wasp-os watches in range')

    c = command('info', cmd_info, 'show the version, battery, memory and more')
    c.add_argument('--json', action='store_true', help='print it as JSON')

    c = command('rtc', cmd_rtc, "check the watch's clock, or set it")
    c.add_argument('action', nargs='?', choices=('check', 'set'), default='check')

    c = command('alarm', cmd_alarm, 'show, set or unset alarms')
    alarm = c.add_subparsers(dest='action', metavar='ACTION')
    c.set_defaults(action='list')
    alarm.add_parser('list', help='show the alarms (the default)', parents=[common])
    a = alarm.add_parser('set', help='add an alarm, or change the one at that time',
                         description='Add an alarm, or change the one at that time.',
                         parents=[common])
    a.add_argument('time', type=parse_time, help='for example 7:30')
    a.add_argument('--days', type=parse_days, default=0,
                   help='when to repeat: ' + ', '.join(REPEATS)
                        + ', or days like mon,wed (default: once)')
    a.add_argument('--off', action='store_true',
                   help='keep it, but switched off')
    a = alarm.add_parser('unset', help='remove the alarm at that time',
                         description='Remove the alarm at that time.',
                         parents=[common])
    a.add_argument('time', help="for example 7:30, or 'all'")

    c = command('face', cmd_face, 'show the watch faces, or choose one')
    c.add_argument('name', nargs='?', help='the watch face to use')

    c = command('notify', cmd_notify, 'show a notification on the watch')
    c.add_argument('title')
    c.add_argument('body')
    c.add_argument('--id', type=int, default=1,
                   help='a new notification with the same id replaces it')

    for name, func, help, arg in (
            ('eval', cmd_eval, 'run Python code on the watch', 'code'),
            ('exec', cmd_exec, 'run a Python file on the watch', 'file')):
        c = command(name, func, help)
        c.add_argument(arg)
        c.add_argument('--exec-timeout', type=float, default=30.0, metavar='SECS',
                       help='seconds to wait for it to finish (default: 30)')

    c = command('push', cmd_push, 'copy a file to the watch')
    c.add_argument('local')
    c.add_argument('remote', nargs='?', help='default: the same name, in /flash')

    c = command('pull', cmd_pull, 'copy a file from the watch')
    c.add_argument('remote')
    c.add_argument('local', nargs='?', help='default: the same name, here')
    c.add_argument('-f', '--force', action='store_true',
                   help='overwrite the local file')

    command('console', cmd_console, 'open a MicroPython prompt on the watch')

    c = command('reset', cmd_reset, 'reboot the watch')
    c.add_argument('--bootloader', action='store_true',
                   help='into the bootloader, ready for an update')

    c = command('ota', cmd_ota, 'update the firmware (micropython.zip)')
    c.add_argument('file')

    c = command('update', cmd_update,
                'update the firmware to the latest published build')
    c.add_argument('--check', action='store_true',
                   help="only show what's new, don't update")
    c.add_argument('-y', '--yes', action='store_true',
                   help="don't ask before updating")
    c.add_argument('--force', action='store_true',
                   help='install the latest build even if it is not newer')
    c.add_argument('--url', default=releases.URL,
                   help=f'where the builds are listed (default: {releases.URL})')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    logging.basicConfig(format='wasptool: %(message)s',
                        level=logging.DEBUG if args.verbose else logging.INFO)
    if not args.verbose:
        # bleak logs its own retries and backend details at INFO
        logging.getLogger('bleak').setLevel(logging.WARNING)
    try:
        sys.exit(asyncio.run(args.func(args)) or 0)
    except KeyboardInterrupt:
        sys.exit(130)
    except (ble.NotFound, ConnectionError, TimeoutError, IOError,
            BleakError, dfu.DfuError, ReplError, watch.NotAvailable,
            releases.ReleaseError) as e:
        print(f'wasptool: {e}', file=sys.stderr)
        sys.exit(1)
