// SPDX-License-Identifier: LGPL-3.0-or-later
// What the companion does on the watch: the Python of wasptool's watch.py,
// printing JSON for the browser instead of Python values.

import {sleep} from '../lib/console.js';

// Sent as several small pieces: the heap on a watch that has been running
// for a while is fragmented, and one big piece may not compile
const INFO = [
  'import gc, os, wasp\ngc.collect()',
  "_i = {'board': os.uname().machine, 'micropython': os.uname().release}",
  'try:\n from version import VERSION\n _i[\'version\'] = VERSION\n' +
  "except ImportError:\n _i['version'] = None",
  "try:\n _i['flash_free'] = os.statvfs('/flash')[0] * os.statvfs('/flash')[4]\n" +
  "except OSError:\n _i['flash_free'] = None",
  "_i['battery'] = wasp.watch.battery.level()\n" +
  "_i['charging'] = bool(wasp.watch.battery.charging())\n" +
  "_i['voltage_mv'] = wasp.watch.battery.voltage_mv()",
  "_i['uptime'] = wasp.watch.rtc.uptime\n_i['time'] = wasp.watch.rtc.get_localtime()",
  "_i['bootloader'] = getattr(wasp.watch, 'bootloader', None)\n" +
  "_i['last_hang'] = getattr(wasp.watch, 'last_hang', None)",
];

export async function info(c) {
  for (const piece of INFO) await c.exec(piece);
  return c.json("gc.collect()\n_i['ram_free'] = gc.mem_free()\n" +
                'print(json.dumps(_i))\ndel _i');
}

// The watch's local time, as a Date in the browser's time zone
const toDate = t => new Date(t[0], t[1] - 1, t[2], t[3], t[4], t[5]);

// Seconds the watch is ahead of this computer (negative: behind)
export async function drift(c) {
  const before = Date.now();
  const t = await c.json('import wasp\nprint(json.dumps(wasp.watch.rtc.get_localtime()))');
  const host = (before + Date.now()) / 2;
  // The watch reports whole seconds: on average it is half a second on
  return Math.round((toDate(t).getTime() + 500 - host) / 1000);
}

// Like Python's time.localtime()[:8]: Monday is 0, the year day counts from 1
export function localtime(date) {
  const yday = Math.round((new Date(date.getFullYear(), date.getMonth(), date.getDate()) -
                           new Date(date.getFullYear(), 0, 1)) / 86400000) + 1;
  return [date.getFullYear(), date.getMonth() + 1, date.getDate(), date.getHours(),
          date.getMinutes(), date.getSeconds(), (date.getDay() + 6) % 7, yday];
}

// Set the watch to this computer's time. The watch only takes whole
// seconds: time a round trip, then send the next second so that it
// arrives as that second starts.
export async function setTime(c) {
  const start = Date.now();
  await c.exec('import wasp');
  const delay = (Date.now() - start) / 2;
  const target = Math.floor((Date.now() + delay) / 1000) * 1000 + 1000;
  await sleep(Math.max(0, target - delay - Date.now()));
  await c.exec(`wasp.watch.rtc.set_localtime((${localtime(new Date(target)).join(', ')}))`);
}

// The Alarm app, when it is enabled (in the Software app)
const ALARM_APP = "import wasp\n_a = [a for a in wasp.system.launcher_ring " +
                  "if type(a).__name__ == 'AlarmApp']\n" +
                  "_a = _a[0] if _a and hasattr(_a[0], 'get_alarms') else None";

export class NotAvailable extends Error {}

async function alarmApp(c) {
  await c.exec(ALARM_APP);
  if ((await c.exec('print(_a is not None)')).trim() !== 'True') {
    throw new NotAvailable('The Alarm app is not enabled (see the Software app ' +
                           'on the watch), or this firmware is too old to set alarms.');
  }
}

// The alarms, as [hour, minute, days]: days is a bit mask with Monday as
// bit 0 and Sunday as bit 6, none for an alarm that goes off once, and
// ALARM_ON set if the alarm is on
export async function alarms(c) {
  await alarmApp(c);
  return c.json('print(json.dumps(_a.get_alarms()))\ndel _a');
}

export async function setAlarms(c, list) {
  if (list.length > MAX_ALARMS) throw new Error(`The watch has room for ${MAX_ALARMS} alarms`);
  await alarmApp(c);
  const tuples = list.map(([h, m, d]) => `(${h | 0}, ${m | 0}, ${d | 0})`).join(', ');
  await c.exec(`_a.set_alarms([${tuples}])\ndel _a`);
}

export const MAX_ALARMS = 4;
export const ALARM_ON = 0x80;
export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const REPEATS = {once: 0, daily: 0x7f, weekdays: 0x1f, weekends: 0x60};

export function formatDays(mask) {
  const days = mask & 0x7f;
  for (const [name, m] of Object.entries(REPEATS)) if (days === m) return name;
  return DAYS.filter((_, i) => days & (1 << i)).join(', ');
}

// The watch faces to choose from, and the one in use, by label
export async function faces(c) {
  const [labels, current] = await c.json(
      'import wasp, appregistry\nprint(json.dumps(([f[1] for f in appregistry.faces_list], ' +
      'type(wasp.system.quick_ring[0]).__name__[:-3])))');
  return {labels, current};
}

// Use the watch face with this label, and keep it after a restart
export async function setFace(c, label) {
  await c.exec('import wasp, appregistry\n' +
               `_f = [f for f in appregistry.faces_list if f[1] == ${JSON.stringify(label)}][0]\n` +
               "_f = '{}.{}App'.format(*_f)");
  await c.exec('_o = wasp.system.quick_ring[0]\n' +
               'wasp.system.register(_f, watch_face=True)\n' +
               "if hasattr(wasp.system, 'save_settings'):\n" +
               '    wasp.system.save_settings(face=_f)\n' +
               'if wasp.system.app is _o:\n' +
               '    wasp.system.switch(wasp.system.quick_ring[0])\n' +
               'del _f, _o');
}

export function buzz(c) {
  return c.exec('import wasp\nwasp.watch.vibrator.pulse(ms=600)');
}
